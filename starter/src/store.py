"""Persistent vector stores with cosine distance + metadata filter.

Default: PostgreSQL + pgvector (starter docker-compose). Alternative: Chroma on disk
(used for the earlier run when Docker was not installed). Both expose the same API:
`upsert(collection, chunks, embed)`, `search(collection, vector, top_k, filters)`,
`count(collection)`, `describe()`. One collection per strategy, same store and metric
for A/B/C. Re-ingesting is idempotent: stable chunk IDs, unchanged chunks (same text
hash) are skipped, obsolete IDs are deleted. If the configured backend is down we
raise; there is no silent fallback to another store.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable

from . import config
from .models import Chunk

HNSW_SETTINGS = {"space": "cosine", "ef_construction": 200, "ef_search": 200}


def _vector_literal(vector: list[float]) -> str:
    return "[" + ",".join(format(float(x), ".8g") for x in vector) + "]"


class PgVectorStore:
    """PostgreSQL + pgvector. Table `chunks` holds every strategy (column `collection`);
    filterable metadata are typed columns, the rest is JSONB. Search is EXACT cosine
    (`ORDER BY embedding <=> query`, sequential scan): at ~3.5k rows per strategy an ANN
    index is unnecessary and exact search avoids filtered-HNSW recall loss."""

    FILTER_COLUMNS = {"book_no": "book_no", "chapter_no": "chapter_no"}

    def __init__(self, database_url: str | None, dimensions: int, model_name: str) -> None:
        import psycopg
        from psycopg.types.json import Jsonb

        if not database_url:
            raise RuntimeError("DATABASE_URL missing: copy starter/.env.example to starter/.env")
        self._psycopg, self._Jsonb = psycopg, Jsonb
        self.url, self.dimensions, self.model_name = database_url, dimensions, model_name
        try:
            with self._connect() as conn:
                server, ext = conn.execute(
                    "SELECT current_setting('server_version'), "
                    "(SELECT extversion FROM pg_extension WHERE extname = 'vector')").fetchone()
        except psycopg.Error as exc:
            raise RuntimeError("PostgreSQL unreachable: start it with "
                               "`docker compose -p day6_student_starter up -d --wait`") from exc
        if not ext:
            raise RuntimeError("pgvector extension missing (see starter/init.sql)")
        self.version = f"PostgreSQL {server.split()[0]} + pgvector {ext}"
        self.create_schema()

    def _connect(self):
        return self._psycopg.connect(self.url, connect_timeout=5)

    def create_schema(self) -> None:
        with self._connect() as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS collections (
                name text PRIMARY KEY, embedding_model text NOT NULL,
                dimensions int NOT NULL, created_at timestamptz NOT NULL DEFAULT now())""")
            conn.execute(f"""CREATE TABLE IF NOT EXISTS chunks (
                collection text NOT NULL REFERENCES collections(name) ON DELETE CASCADE,
                chunk_id text NOT NULL,
                document_id text NOT NULL,
                source text NOT NULL,
                page int NOT NULL,
                page_end int NOT NULL,
                book_no int NOT NULL,
                chapter_no int NOT NULL,
                text text NOT NULL,
                text_sha1 char(40) NOT NULL,
                metadata jsonb NOT NULL,
                embedding vector({self.dimensions}) NOT NULL,
                updated_at timestamptz NOT NULL DEFAULT now(),
                PRIMARY KEY (collection, chunk_id))""")
            conn.execute("CREATE INDEX IF NOT EXISTS chunks_filter_idx "
                         "ON chunks (collection, book_no, chapter_no)")
            dims = conn.execute("SELECT atttypmod FROM pg_attribute WHERE attrelid = 'chunks'::regclass "
                                "AND attname = 'embedding'").fetchone()[0]
        if dims != self.dimensions:
            raise ValueError(f"Table chunks has vector({dims}); model produces {self.dimensions}.")

    def _collection(self, conn, name: str) -> None:
        conn.execute("INSERT INTO collections (name, embedding_model, dimensions) VALUES (%s, %s, %s) "
                     "ON CONFLICT (name) DO NOTHING", (name, self.model_name, self.dimensions))
        model, dims = conn.execute("SELECT embedding_model, dimensions FROM collections WHERE name = %s",
                                   (name,)).fetchone()
        if model != self.model_name or dims != self.dimensions:
            raise ValueError(f"Collection {name} was built with {model}/{dims}; refusing to mix models.")

    def count(self, collection: str) -> int:
        with self._connect() as conn:
            return conn.execute("SELECT count(*) FROM chunks WHERE collection = %s", (collection,)).fetchone()[0]

    def upsert(self, collection: str, chunks: list[Chunk],
               embed: Callable[[list[str]], list[list[float]]],
               batch_size: int = 256) -> dict[str, int]:
        ids = [c.chunk_id for c in chunks]
        if len(set(ids)) != len(ids):
            raise ValueError("Duplicate chunk IDs in one ingest run")
        with self._connect() as conn:
            self._collection(conn, collection)
            existing = dict(conn.execute("SELECT chunk_id, text_sha1 FROM chunks WHERE collection = %s",
                                         (collection,)).fetchall())
        todo = [c for c in chunks if existing.get(c.chunk_id) != c.metadata["text_sha1"]]
        obsolete = sorted(set(existing) - set(ids))
        sql = """INSERT INTO chunks (collection, chunk_id, document_id, source, page, page_end, book_no,
                                     chapter_no, text, text_sha1, metadata, embedding)
                 VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::vector)
                 ON CONFLICT (collection, chunk_id) DO UPDATE SET
                   document_id = EXCLUDED.document_id, source = EXCLUDED.source, page = EXCLUDED.page,
                   page_end = EXCLUDED.page_end, book_no = EXCLUDED.book_no,
                   chapter_no = EXCLUDED.chapter_no, text = EXCLUDED.text,
                   text_sha1 = EXCLUDED.text_sha1, metadata = EXCLUDED.metadata,
                   embedding = EXCLUDED.embedding, updated_at = now()"""
        for i in range(0, len(todo), batch_size):
            batch = todo[i:i + batch_size]
            vectors = embed([c.text for c in batch])
            if len(vectors) != len(batch) or any(len(v) != self.dimensions for v in vectors):
                raise ValueError("Embedding count/dimension mismatch")
            rows = [(collection, c.chunk_id, c.document_id, c.source, c.page, c.metadata["page_end"],
                     c.metadata["book_no"], c.metadata["chapter_no"], c.text, c.metadata["text_sha1"],
                     self._Jsonb(c.metadata), _vector_literal(v)) for c, v in zip(batch, vectors)]
            with self._connect() as conn:  # one transaction per batch
                with conn.cursor() as cur:
                    cur.executemany(sql, rows)
        with self._connect() as conn:
            if obsolete:
                conn.execute("DELETE FROM chunks WHERE collection = %s AND chunk_id = ANY(%s)",
                             (collection, obsolete))
            count_after = conn.execute("SELECT count(*) FROM chunks WHERE collection = %s",
                                       (collection,)).fetchone()[0]
        return {"chunks_in_run": len(chunks), "embedded_or_updated": len(todo),
                "unchanged_skipped": len(chunks) - len(todo), "obsolete_deleted": len(obsolete),
                "count_after": count_after}

    def search(self, collection: str, query_vector: list[float], top_k: int = 3,
               filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        if len(query_vector) != self.dimensions:
            raise ValueError("Query vector dimension mismatch")
        where, params = ["collection = %s"], [collection]
        for key, value in (filters or {}).items():
            if key not in self.FILTER_COLUMNS:  # whitelist column names; values are parameters
                raise ValueError(f"Filter on {key!r} not allowed")
            where.append(f"{self.FILTER_COLUMNS[key]} = %s")
            params.append(value)
        qv = _vector_literal(query_vector)
        sql = (f"SELECT chunk_id, text, document_id, source, page, page_end, book_no, chapter_no, metadata, "
               f"embedding <=> %s::vector AS distance FROM chunks WHERE {' AND '.join(where)} "
               f"ORDER BY distance LIMIT %s")
        if getattr(self, "_search_conn", None) is None or self._search_conn.closed:
            self._search_conn = self._psycopg.connect(self.url, connect_timeout=5, autocommit=True)
        rows = self._search_conn.execute(sql, [qv, *params, top_k]).fetchall()  # reused connection
        hits = []
        for rank, (cid, text, doc, src, page, page_end, book, chapter, meta, dist) in enumerate(rows, 1):
            hits.append({"rank": rank, "chunk_id": cid, "score": round(1.0 - float(dist), 4), "text": text,
                         "metadata": {**meta, "document_id": doc, "source": src, "page": page,
                                      "page_end": page_end, "book_no": book, "chapter_no": chapter}})
        return hits

    def describe(self) -> dict[str, Any]:
        safe_url = re.sub(r"//([^:@/]+):[^@]*@", r"//\1:***@", self.url)
        return {"name": "PostgreSQL + pgvector (docker compose, volume pg_data)", "version": self.version,
                "connection": safe_url, "table": "chunks (one `collection` value per strategy)",
                "metric": "cosine distance (<=>)",
                "search": "exact: ORDER BY embedding <=> query LIMIT k (sequential scan, no ANN index)",
                "filter": "SQL WHERE on typed columns book_no / chapter_no (whitelisted, parameterized)"}


def make_store(dimensions: int, model_name: str):
    """Build the configured store. Raises if it is unavailable (no silent fallback)."""
    if config.VECTOR_STORE == "pgvector":
        return PgVectorStore(config.DATABASE_URL, dimensions, model_name)
    if config.VECTOR_STORE == "chroma":
        return ChromaStore(config.INDEX_DIR, dimensions, model_name)
    raise ValueError(f"Unknown VECTOR_STORE={config.VECTOR_STORE!r} (use pgvector or chroma)")


class ChromaStore:
    def __init__(self, path: Path, dimensions: int, model_name: str) -> None:
        import chromadb

        self.version = chromadb.__version__
        self.dimensions = dimensions
        self.model_name = model_name
        path.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._client = chromadb.PersistentClient(path=str(path))

    def _collection(self, name: str):
        try:
            col = self._client.get_or_create_collection(
                name=name, embedding_function=None, configuration={"hnsw": HNSW_SETTINGS},
                metadata={"embedding_model": self.model_name, "dimensions": self.dimensions})
        except TypeError:  # older chromadb without `configuration`
            col = self._client.get_or_create_collection(
                name=name, embedding_function=None,
                metadata={"hnsw:space": "cosine", "hnsw:construction_ef": 200,
                          "hnsw:search_ef": 200, "embedding_model": self.model_name,
                          "dimensions": self.dimensions})
        meta = col.metadata or {}
        if meta.get("embedding_model") not in (None, self.model_name) or \
                meta.get("dimensions") not in (None, self.dimensions):
            raise ValueError(f"Collection {name} was built with {meta}; refusing to mix models.")
        return col

    def count(self, collection: str) -> int:
        return self._collection(collection).count()

    def describe(self) -> dict[str, Any]:
        return {"name": "chroma (PersistentClient)", "version": self.version,
                "path": str(self.path.relative_to(config.REPO_ROOT)), "metric": "cosine",
                "search": "HNSW (approximate)", "hnsw": {k: v for k, v in HNSW_SETTINGS.items() if k != "space"},
                "filter": "where={field: {$eq: value}}"}

    def upsert(self, collection: str, chunks: list[Chunk],
               embed: Callable[[list[str]], list[list[float]]],
               batch_size: int = 256) -> dict[str, int]:
        """Embed only new/changed chunks, write them, delete IDs no longer produced."""
        col = self._collection(collection)
        ids = [c.chunk_id for c in chunks]
        if len(set(ids)) != len(ids):
            raise ValueError("Duplicate chunk IDs in one ingest run")
        existing: dict[str, str] = {}
        all_ids = col.get(include=[])["ids"]
        for i in range(0, len(all_ids), 5000):
            got = col.get(ids=all_ids[i:i + 5000], include=["metadatas"])
            existing.update({cid: (m or {}).get("text_sha1") for cid, m in zip(got["ids"], got["metadatas"])})
        todo = [c for c in chunks if existing.get(c.chunk_id) != c.metadata["text_sha1"]]
        obsolete = sorted(set(existing) - set(ids))
        for i in range(0, len(todo), batch_size):
            batch = todo[i:i + batch_size]
            vectors = embed([c.text for c in batch])
            if len(vectors) != len(batch) or any(len(v) != self.dimensions for v in vectors):
                raise ValueError("Embedding count/dimension mismatch")
            col.upsert(ids=[c.chunk_id for c in batch], embeddings=vectors,
                       documents=[c.text for c in batch],
                       metadatas=[self._metadata(c) for c in batch])
        for i in range(0, len(obsolete), 5000):
            col.delete(ids=obsolete[i:i + 5000])
        return {"chunks_in_run": len(chunks), "embedded_or_updated": len(todo),
                "unchanged_skipped": len(chunks) - len(todo), "obsolete_deleted": len(obsolete),
                "count_after": col.count()}

    @staticmethod
    def _metadata(chunk: Chunk) -> dict[str, Any]:
        meta = {"document_id": chunk.document_id, "source": chunk.source, "page": chunk.page}
        meta.update({k: v for k, v in chunk.metadata.items() if v is not None})
        return meta

    def search(self, collection: str, query_vector: list[float], top_k: int = 3,
               filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Cosine top-k; `filters` is an exact-match dict on whitelisted metadata."""
        if len(query_vector) != self.dimensions:
            raise ValueError("Query vector dimension mismatch")
        where = None
        if filters:
            clauses = [{key: {"$eq": value}} for key, value in filters.items()]
            where = clauses[0] if len(clauses) == 1 else {"$and": clauses}
        res = self._collection(collection).query(
            query_embeddings=[query_vector], n_results=top_k, where=where,
            include=["documents", "metadatas", "distances"])
        hits = []
        for rank, (cid, doc, meta, dist) in enumerate(zip(res["ids"][0], res["documents"][0],
                                                          res["metadatas"][0], res["distances"][0]), 1):
            hits.append({"rank": rank, "chunk_id": cid, "score": round(1.0 - float(dist), 4),
                         "text": doc, "metadata": meta})
        return hits
