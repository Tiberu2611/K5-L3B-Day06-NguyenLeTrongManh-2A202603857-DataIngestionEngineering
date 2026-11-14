"""Real local embedding model via Sentence Transformers (no API key, no data upload).

There is deliberately no mock/random fallback: if the model cannot load, we fail.
"""
from __future__ import annotations

from pathlib import Path
from typing import Protocol

from . import config


class Embedder(Protocol):
    model_name: str
    dimensions: int

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...
    def embed_query(self, question: str) -> list[float]: ...


class SentenceTransformerEmbedder:
    """E5-style model: prefix 'passage: ' for documents and 'query: ' for queries,
    L2-normalized vectors so cosine distance in the store is well defined."""

    def __init__(self, model_name: str = config.EMBEDDING_MODEL,
                 query_prefix: str = config.QUERY_PREFIX,
                 passage_prefix: str = config.PASSAGE_PREFIX,
                 batch_size: int = config.EMBED_BATCH_SIZE) -> None:
        import sentence_transformers
        import torch
        from sentence_transformers import SentenceTransformer

        self.model_name = model_name
        self.query_prefix, self.passage_prefix = query_prefix, passage_prefix
        self.batch_size = batch_size
        torch.manual_seed(config.SEED)
        self._model = SentenceTransformer(model_name, device="cpu")
        get_dim = getattr(self._model, "get_embedding_dimension", None) or \
            self._model.get_sentence_embedding_dimension
        self.dimensions = int(get_dim())
        self.max_seq_length = int(self._model.max_seq_length)
        try:  # commit hash of the cached snapshot actually used
            from huggingface_hub import snapshot_download
            self.revision = Path(snapshot_download(model_name, local_files_only=True)).name
        except Exception:
            self.revision = "unknown"
        self.library_versions = {"sentence-transformers": sentence_transformers.__version__,
                                 "torch": torch.__version__}

    def _encode(self, texts: list[str], show_progress: bool) -> list[list[float]]:
        vectors = self._model.encode(texts, batch_size=self.batch_size, normalize_embeddings=True,
                                     convert_to_numpy=True, show_progress_bar=show_progress)
        return vectors.tolist()

    def count_tokens(self, texts: list[str]) -> list[int]:
        tok = self._model.tokenizer
        return [len(ids) for ids in tok([self.passage_prefix + t for t in texts],
                                        add_special_tokens=True)["input_ids"]]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._encode([self.passage_prefix + t for t in texts], show_progress=len(texts) > 200)

    def embed_query(self, question: str) -> list[float]:
        return self._encode([self.query_prefix + question], show_progress=False)[0]

    def describe(self) -> dict:
        return {"provider": "local (sentence-transformers, CPU)", "model": self.model_name,
                "model_source": f"https://huggingface.co/{self.model_name}",
                "model_license": "MIT (model card)" if self.model_name == "intfloat/multilingual-e5-small" else "see model card",
                "revision": self.revision, "dimensions": self.dimensions,
                "max_seq_length_tokens": self.max_seq_length,
                "query_processing": f"prefix {self.query_prefix!r}, L2-normalized",
                "document_processing": f"prefix {self.passage_prefix!r}, L2-normalized",
                "cost_usd": 0.0, **self.library_versions}
