"""Store and search vectors using PostgreSQL + pgvector (exact cosine search)."""
import json
from typing import Any

import psycopg

from .models import Chunk

TABLE = "chunks"
# Filter keys a caller may use, mapped to real columns (never interpolate user keys).
FILTER_COLUMNS = {"book": "book", "chapter": "chapter", "document_id": "document_id"}


def _vector_literal(vector: list[float]) -> str:
    return "[" + ",".join(f"{x:.7f}" for x in vector) + "]"


class PgVectorStore:
    def __init__(self, database_url: str, dimensions: int) -> None:
        if not database_url:
            raise ValueError("DATABASE_URL is empty: copy starter/.env.example to starter/.env")
        if dimensions <= 0:
            raise ValueError(f"Invalid embedding dimensions: {dimensions}")
        self.database_url = database_url
        self.dimensions = dimensions

    def _connect(self) -> psycopg.Connection:
        return psycopg.connect(self.database_url, connect_timeout=5)

    def create_schema(self) -> None:
        with self._connect() as conn:
            conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
            conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {TABLE} (
                    strategy     text    NOT NULL,
                    chunk_id     text    NOT NULL,
                    document_id  text    NOT NULL,
                    source       text    NOT NULL,
                    page         integer NOT NULL,
                    book         integer,
                    chapter      integer,
                    content      text    NOT NULL,
                    content_hash text    NOT NULL,
                    model_name   text    NOT NULL,
                    metadata     jsonb   NOT NULL DEFAULT '{{}}'::jsonb,
                    embedding    vector({self.dimensions}) NOT NULL,
                    updated_at   timestamptz NOT NULL DEFAULT now(),
                    PRIMARY KEY (strategy, chunk_id)
                )""")
            conn.execute(f"CREATE INDEX IF NOT EXISTS {TABLE}_strategy_book_idx ON {TABLE} (strategy, book)")
            row = conn.execute(
                "SELECT format_type(atttypid, atttypmod) FROM pg_attribute "
                "WHERE attrelid = %s::regclass AND attname = 'embedding'", (TABLE,)).fetchone()
            if row and row[0] != f"vector({self.dimensions})":
                raise RuntimeError(f"Existing table uses {row[0]}, model gives vector({self.dimensions}). "
                                   "Use a new table/database instead of mixing models.")

    def existing_hashes(self, strategy: str) -> dict[str, tuple[str, str]]:
        """chunk_id -> (content_hash, model_name) for re-ingest without re-embedding."""
        with self._connect() as conn:
            rows = conn.execute(f"SELECT chunk_id, content_hash, model_name FROM {TABLE} WHERE strategy = %s",
                                (strategy,)).fetchall()
        return {r[0]: (r[1], r[2]) for r in rows}

    def upsert(self, strategy: str, chunks: list[Chunk], vectors: list[list[float]],
               model_name: str = "") -> int:
        """Insert/update chunks by stable ID (re-running never duplicates rows).

        Call ``delete_obsolete`` afterwards with the full list of current IDs to
        remove chunks that disappeared because a source document changed.
        """
        if len(chunks) != len(vectors):
            raise ValueError(f"{len(chunks)} chunks but {len(vectors)} vectors")
        for vector in vectors:
            if len(vector) != self.dimensions:
                raise ValueError(f"Vector has {len(vector)} dims, store expects {self.dimensions}")
        with self._connect() as conn, conn.cursor() as cur:
            for chunk, vector in zip(chunks, vectors):
                meta = dict(chunk.metadata)
                cur.execute(f"""
                    INSERT INTO {TABLE} (strategy, chunk_id, document_id, source, page, book, chapter,
                                         content, content_hash, model_name, metadata, embedding)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::vector)
                    ON CONFLICT (strategy, chunk_id) DO UPDATE SET
                        document_id = EXCLUDED.document_id, source = EXCLUDED.source,
                        page = EXCLUDED.page, book = EXCLUDED.book, chapter = EXCLUDED.chapter,
                        content = EXCLUDED.content, content_hash = EXCLUDED.content_hash,
                        model_name = EXCLUDED.model_name, metadata = EXCLUDED.metadata,
                        embedding = EXCLUDED.embedding, updated_at = now()""",
                    (strategy, chunk.chunk_id, chunk.document_id, chunk.source, chunk.page,
                     meta.get("book"), meta.get("chapter"), chunk.text, meta["content_hash"],
                     model_name, json.dumps(meta, ensure_ascii=False), _vector_literal(vector)))
        return len(chunks)

    def delete_obsolete(self, strategy: str, documents: list[str], keep_ids: list[str]) -> int:
        with self._connect() as conn:
            cur = conn.execute(f"""DELETE FROM {TABLE} WHERE strategy = %s AND document_id = ANY(%s)
                                   AND NOT (chunk_id = ANY(%s))""", (strategy, documents, keep_ids))
            return cur.rowcount

    def count(self, strategy: str) -> int:
        with self._connect() as conn:
            return conn.execute(f"SELECT count(*) FROM {TABLE} WHERE strategy = %s", (strategy,)).fetchone()[0]

    def duplicate_count(self, strategy: str) -> int:
        """Rows sharing (document_id, page, content_hash): should be 0 after any re-ingest."""
        with self._connect() as conn:
            return conn.execute(f"""SELECT coalesce(sum(n - 1), 0) FROM (
                SELECT count(*) AS n FROM {TABLE} WHERE strategy = %s
                GROUP BY document_id, page, content_hash, metadata->>'char_start') t""", (strategy,)).fetchone()[0]

    def search(self, strategy: str, query_vector: list[float], top_k: int = 3,
               filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        if len(query_vector) != self.dimensions:
            raise ValueError(f"Query vector has {len(query_vector)} dims, expected {self.dimensions}")
        where, params = ["strategy = %s"], [strategy]
        for key, value in (filters or {}).items():
            if key not in FILTER_COLUMNS:
                raise ValueError(f"Filter '{key}' not allowed; use one of {sorted(FILTER_COLUMNS)}")
            values = value if isinstance(value, list) else [value]
            where.append(f"{FILTER_COLUMNS[key]} = ANY(%s)")
            params.append(values)
        literal = _vector_literal(query_vector)
        sql = f"""SELECT chunk_id, document_id, source, page, book, chapter, content, metadata,
                         1 - (embedding <=> %s::vector) AS score
                  FROM {TABLE} WHERE {' AND '.join(where)}
                  ORDER BY embedding <=> %s::vector, chunk_id LIMIT %s"""
        with self._connect() as conn:
            rows = conn.execute(sql, [literal, *params, literal, top_k]).fetchall()
        return [{"chunk_id": r[0], "document_id": r[1], "source": r[2], "page": r[3], "book": r[4],
                 "chapter": r[5], "text": r[6], "metadata": r[7], "score": float(r[8])} for r in rows]
