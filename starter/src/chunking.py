"""Fixed-size (A) and paragraph-aware (B/C) chunking.

Both strategies work on the same per-chapter text stream (pages joined in order,
a paragraph that runs over a page break is re-joined) and map every chunk back to
its start/end PDF page. Chunks never cross chapter boundaries.
"""
from __future__ import annotations

import bisect
import hashlib
import re
from dataclasses import dataclass, field
from itertools import groupby

from .models import Chunk, DocumentPage

_SENTENCE_END = re.compile(r"(?<=[.!?…])[”’\"']?\s+(?=[“‘\"'A-Z])")


@dataclass
class ChapterStream:
    document_id: str
    source: str
    metadata: dict
    text: str = ""
    page_starts: list[int] = field(default_factory=list)   # stream offsets where a page begins
    page_numbers: list[int] = field(default_factory=list)
    paragraphs: list[tuple[int, int]] = field(default_factory=list)  # (start, end) offsets

    def page_at(self, offset: int) -> int:
        return self.page_numbers[bisect.bisect_right(self.page_starts, offset) - 1]


def build_streams(pages: list[DocumentPage]) -> list[ChapterStream]:
    streams: list[ChapterStream] = []
    key = lambda p: (p.metadata["book_no"], p.metadata["chapter_no"])
    for _, group in groupby(pages, key=key):
        group = list(group)
        first = group[0]
        meta = {k: first.metadata[k] for k in ("book_no", "book_title", "chapter_no", "chapter_title")}
        stream = ChapterStream(first.document_id, first.source, meta)
        parts: list[str] = []
        length = 0
        para_start = None
        for page in group:
            paras = page.text.split("\n")
            for i, para in enumerate(paras):
                continuation = i == 0 and page.metadata.get("continues_previous_page") and parts
                sep = " " if continuation else ("\n" if parts else "")
                if not continuation and para_start is not None:
                    stream.paragraphs.append((para_start, length))
                parts.append(sep)
                length += len(sep)
                if i == 0:
                    stream.page_starts.append(length)
                    stream.page_numbers.append(page.page)
                if not continuation:
                    para_start = length
                parts.append(para)
                length += len(para)
        if para_start is not None:
            stream.paragraphs.append((para_start, length))
        stream.text = "".join(parts)
        streams.append(stream)
    return streams


def _make_chunk(stream: ChapterStream, strategy: str, index: int, start: int, end: int) -> Chunk | None:
    raw = stream.text[start:end]
    lead = len(raw) - len(raw.lstrip())
    text = raw.strip()
    if not text:
        return None
    start += lead
    end = start + len(text)
    page, page_end = stream.page_at(start), stream.page_at(end - 1)
    meta = dict(stream.metadata)
    meta.update({"page_end": page_end, "strategy": strategy, "chunk_index": index,
                 "char_count": len(text), "text_sha1": hashlib.sha1(text.encode()).hexdigest(),
                 "stream_start": start, "stream_end": end})
    chunk_id = f"{strategy}-b{meta['book_no']}-c{meta['chapter_no']:02d}-{index:04d}"
    return Chunk(chunk_id, stream.document_id, stream.source, page, text, meta)


def fixed_size(stream: ChapterStream, strategy: str, size: int, overlap: int) -> list[Chunk]:
    """Sliding windows of `size` chars with `overlap`; ends snapped back to a space
    (never cut inside a word) but sentence/paragraph structure is ignored."""
    if not 0 <= overlap < size:
        raise ValueError("overlap must be in [0, size)")
    text, chunks, start = stream.text, [], 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            cut = max(text.rfind(" ", start + size // 2, end), text.rfind("\n", start + size // 2, end))
            end = cut if cut > start else end
        chunk = _make_chunk(stream, strategy, len(chunks), start, end)
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        nxt = max(end - overlap, start + 1)
        while nxt < end and not text[nxt - 1].isspace():   # start on a word boundary
            nxt += 1
        start = nxt
    return chunks


def _split_long(start: int, end: int, text: str, max_size: int) -> list[tuple[int, int]]:
    """Split one oversized paragraph at sentence ends (then spaces) into <= max_size spans."""
    cuts = [start] + [start + m.end() for m in _SENTENCE_END.finditer(text[start:end])] + [end]
    spans, cur = [], start
    for a, b in zip(cuts, cuts[1:]):
        if b - cur > max_size and a > cur:
            spans.append((cur, a))
            cur = a
        while b - cur > max_size:                    # single very long sentence
            cut = text.rfind(" ", cur, cur + max_size)
            cut = cut if cut > cur else cur + max_size
            spans.append((cur, cut))
            cur = cut
    spans.append((cur, end))
    return [(a, b) for a, b in spans if text[a:b].strip()]


def by_paragraph(stream: ChapterStream, strategy: str, max_size: int) -> list[Chunk]:
    """Greedily pack whole paragraphs up to `max_size` chars; split only paragraphs
    that are themselves longer than `max_size` (at sentence boundaries)."""
    pieces: list[tuple[int, int]] = []
    for start, end in stream.paragraphs:
        pieces.extend(_split_long(start, end, stream.text, max_size) if end - start > max_size
                      else [(start, end)])
    chunks: list[Chunk] = []
    cur_start = cur_end = None
    for start, end in pieces:
        if cur_start is None:
            cur_start, cur_end = start, end
        elif end - cur_start <= max_size:
            cur_end = end
        else:
            chunk = _make_chunk(stream, strategy, len(chunks), cur_start, cur_end)
            if chunk:
                chunks.append(chunk)
            cur_start, cur_end = start, end
    if cur_start is not None:
        chunk = _make_chunk(stream, strategy, len(chunks), cur_start, cur_end)
        if chunk:
            chunks.append(chunk)
    return chunks


def build_chunks(streams: list[ChapterStream], strategy: str, params: dict) -> list[Chunk]:
    out: list[Chunk] = []
    for stream in streams:
        if params["chunking"] == "fixed":
            out.extend(fixed_size(stream, strategy, params["size"], params["overlap"]))
        elif params["chunking"] == "paragraph":
            out.extend(by_paragraph(stream, strategy, params["max_size"]))
        else:
            raise ValueError(f"Unknown chunking {params['chunking']!r}")
    return out
