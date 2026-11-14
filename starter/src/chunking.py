"""Fixed-size and structure-aware (paragraph) chunking.

Both strategies work page by page so every chunk keeps an exact physical page
number for traceability. Page text uses "\n\n" between paragraphs (see
ingestion.normalize_text).
"""
import hashlib
import re

from .models import Chunk, DocumentPage

# A line like "CHAPTER ONE" / "Chapter 12" starts a new chunk in by_paragraph.
HEADING = re.compile(r"^\s*chapter\s+[\w-]+\s*$", re.IGNORECASE)
# Sentence end: . ! ? (optionally followed by closing quotes) + space.
SENTENCE_END = re.compile(r"(?<=[.!?])[\"')\]]*\s+")


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _make_chunk(page: DocumentPage, tag: str, index: int, start: int, end: int,
                extra: dict | None = None) -> Chunk:
    text = page.text[start:end].strip()
    meta = {**page.metadata, "strategy_tag": tag, "char_start": start, "char_end": end,
            "n_chars": len(text), "content_hash": content_hash(text), **(extra or {})}
    return Chunk(chunk_id=f"{page.document_id}:{tag}:p{page.page:04d}:{index:02d}",
                 document_id=page.document_id, source=page.source, page=page.page,
                 text=text, metadata=meta)


def fixed_size(page: DocumentPage, size: int, overlap: int) -> list[Chunk]:
    """Character windows of ``size`` with ``overlap``; ignores sentence/paragraph limits."""
    if size <= 0 or not 0 <= overlap < size:
        raise ValueError("Need size > 0 and 0 <= overlap < size")
    tag, step, chunks = f"fx{size}o{overlap}", size - overlap, []
    text = page.text
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        if text[start:end].strip():
            chunks.append(_make_chunk(page, tag, len(chunks), start, end))
        if end == len(text):
            break
        start += step
    return chunks


def _paragraph_spans(text: str) -> list[tuple[int, int]]:
    spans, pos = [], 0
    for part in text.split("\n\n"):
        start = text.index(part, pos) if part else pos
        end = start + len(part)
        if part.strip():
            spans.append((start, end))
        pos = end
    return spans


def _split_long(text: str, start: int, end: int, max_size: int) -> list[tuple[int, int]]:
    """Split an oversized paragraph at sentence ends; hard-split only giant sentences."""
    pieces, cur = [], start
    for match in SENTENCE_END.finditer(text, start, end):
        pieces.append((cur, match.end()))
        cur = match.end()
    if cur < end:
        pieces.append((cur, end))
    out = []
    for s, e in pieces:
        while e - s > max_size:  # a single sentence longer than max_size
            out.append((s, s + max_size))
            s += max_size
        out.append((s, e))
    return out


def by_paragraph(page: DocumentPage, max_size: int) -> list[Chunk]:
    """Pack whole paragraphs up to ``max_size`` chars; a chapter heading starts a new chunk."""
    if max_size <= 0:
        raise ValueError("max_size must be > 0")
    tag, text = f"par{max_size}", page.text
    units: list[tuple[int, int, bool]] = []  # (start, end, is_heading)
    for s, e in _paragraph_spans(text):
        if e - s > max_size:
            units.extend((a, b, False) for a, b in _split_long(text, s, e, max_size))
        else:
            units.append((s, e, bool(HEADING.match(text[s:e]))))

    groups: list[tuple[int, int, int]] = []  # (start, end, n_units)
    for s, e, is_heading in units:
        if groups and not is_heading and e - groups[-1][0] <= max_size:
            gs, _, n = groups[-1]
            groups[-1] = (gs, e, n + 1)
        else:
            groups.append((s, e, 1))
    return [_make_chunk(page, tag, i, s, e, {"n_units": n}) for i, (s, e, n) in enumerate(groups)]
