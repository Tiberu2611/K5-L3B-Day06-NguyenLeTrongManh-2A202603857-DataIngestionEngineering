"""Real embedding provider: a local Sentence Transformers model.

The same model, prefix and normalisation are used for every strategy. There is
no mock or random fallback: if the model cannot be loaded, the pipeline stops.
"""
from typing import Protocol


class Embedder(Protocol):
    model_name: str
    dimensions: int

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Return one vector per input text, in the same order."""
        ...

    def embed_query(self, question: str) -> list[float]:
        """Return a query vector compatible with the stored document vectors."""
        ...


# BGE retrieval models expect this instruction on queries only (model card).
BGE_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "


class MyEmbedder:
    """Local Sentence Transformers adapter (CPU by default).

    Documents are embedded as-is; queries get ``query_prefix``. Vectors are
    L2-normalised so cosine distance in pgvector equals 1 - dot product.
    """

    def __init__(self, model_name: str, query_prefix: str | None = None,
                 batch_size: int = 32, device: str = "cpu") -> None:
        from sentence_transformers import SentenceTransformer  # heavy import

        self.model_name = model_name
        self.query_prefix = BGE_QUERY_PREFIX if query_prefix is None and "bge" in model_name.lower() \
            else (query_prefix or "")
        self.batch_size = batch_size
        self._model = SentenceTransformer(model_name, device=device)
        dims = self._model.get_sentence_embedding_dimension()
        if not dims:
            raise RuntimeError(f"Cannot determine embedding dimensions for {model_name}")
        self.dimensions = int(dims)
        self.max_seq_length = int(self._model.max_seq_length)

    def count_tokens(self, text: str) -> int:
        return len(self._model.tokenizer.tokenize(text))

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        vectors = self._model.encode(texts, batch_size=self.batch_size, normalize_embeddings=True,
                                     show_progress_bar=False, convert_to_numpy=True)
        return vectors.tolist()

    def embed_query(self, question: str) -> list[float]:
        vector = self._model.encode([self.query_prefix + question], normalize_embeddings=True,
                                    show_progress_bar=False, convert_to_numpy=True)[0]
        return vector.tolist()
