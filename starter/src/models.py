"""Shared data contracts; keep traceability from chunk back to source."""
from dataclasses import dataclass, field
from typing import Any


@dataclass
class DocumentPage:
    document_id: str
    source: str
    page: int                      # physical PDF page number (1-based)
    text: str                      # normalized; one paragraph per line
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Chunk:
    chunk_id: str
    document_id: str
    source: str
    page: int                      # page where the chunk starts
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)  # includes page_end, book_no, chapter_no
