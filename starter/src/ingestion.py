"""Read and normalize the PDF corpus, keeping page-level traceability.

Book and chapter metadata come from the PDF outline (bookmarks), never guessed.
Paragraph boundaries are rebuilt from text positions: in this PDF the first line
of each paragraph is indented (x = margin + 14.4pt) and preceded by a larger gap.
"""
from __future__ import annotations

import hashlib
import json
import re
import statistics
import time
import unicodedata
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pypdf

from .models import DocumentPage

INGESTION_VERSION = "2026-11-14.v3"
_CHAPTER_RE = re.compile(r"^Chapter\s+(\d+)\s*-\s*(.+)$")
_SPACES_RE = re.compile(r"[ \t  -​]+")


# ---------------------------------------------------------------- outline ----
def read_outline(reader: pypdf.PdfReader) -> list[dict[str, Any]]:
    """Return chapters [{book_no, book_title, chapter_no, chapter_title, start, end}]."""
    flat: list[tuple[int, str, int]] = []

    def walk(items, depth=0):
        for item in items:
            if isinstance(item, list):
                walk(item, depth + 1)
            else:
                flat.append((depth, item.title, reader.get_destination_page_number(item) + 1))

    walk(reader.outline)
    chapters: list[dict[str, Any]] = []
    book_no, book_title = 0, None
    for i, (depth, title, page) in enumerate(flat):
        title = normalize_text(title)
        if depth == 0 and title.startswith("Harry Potter and"):
            book_no += 1
            book_title = title
        elif depth == 1 and book_title:
            m = _CHAPTER_RE.match(title)
            if m:
                next_start = flat[i + 1][2] if i + 1 < len(flat) else len(reader.pages) + 1
                chapters.append({"book_no": book_no, "book_title": book_title,
                                 "chapter_no": int(m.group(1)), "chapter_title": m.group(2),
                                 "start": page, "end": next_start - 1})
    return chapters


# ---------------------------------------------------------- normalization ----
def normalize_text(text: str) -> str:
    """NFC Unicode, tabs/odd spaces -> one space, trim. Keeps quotes/dashes as in source."""
    text = unicodedata.normalize("NFC", text)
    return _SPACES_RE.sub(" ", text).strip()


def _page_lines(page: pypdf.PageObject) -> list[dict[str, Any]]:
    """Group positioned text segments into visual lines (top to bottom)."""
    segments: list[tuple[float, float, str]] = []

    def visitor(text, cm, tm, _font, _size):
        if text and text.strip():
            x = tm[4] * cm[0] + tm[5] * cm[2] + cm[4]
            y = tm[4] * cm[1] + tm[5] * cm[3] + cm[5]
            segments.append((y, x, text))

    page.extract_text(visitor_text=visitor)
    lines: list[dict[str, Any]] = []
    for y, x, text in sorted(segments, key=lambda s: (-s[0], s[1])):
        if lines and abs(lines[-1]["y"] - y) < 1.0:
            lines[-1]["text"] += text
        else:
            lines.append({"y": y, "x": x, "text": text})
    for line in lines:
        line["text"] = normalize_text(line["text"].replace("\n", " "))
    return [line for line in lines if line["text"]]


def _paragraphs(lines: list[dict[str, Any]], margin: float, is_chapter_start: bool,
                log: dict[str, Any], page_no: int) -> tuple[list[str], bool]:
    """Rebuild paragraphs. Returns (paragraphs, first_paragraph_continues_previous_page)."""
    if is_chapter_start:
        drop = [ln for ln in lines if re.fullmatch(r"[A-Z]", ln["text"])]
        heading = []
        for ln in lines:  # "CHAPTER N" + title: the leading run of lines without lowercase
            if ln in drop:
                continue
            if re.search(r"[a-z]", ln["text"]):
                break
            heading.append(ln)
        body = [ln for ln in lines if ln not in drop and ln not in heading]
        if drop and body:
            body[0] = {**body[0], "text": drop[0]["text"] + body[0]["text"]}
            log["drop_caps_joined"].append(page_no)
        else:
            log["chapter_start_without_drop_cap"].append(page_no)
        log["heading_lines_removed"] += len(heading)
        lines = body
    numeric = [ln for ln in lines if re.fullmatch(r"\d{1,4}", ln["text"])]
    if numeric:
        log["page_number_lines_removed"] += len(numeric)
        lines = [ln for ln in lines if ln not in numeric]
    if not lines:
        return [], False

    gaps = sorted(lines[i - 1]["y"] - lines[i]["y"] for i in range(1, len(lines)))
    # Lower quartile = spacing inside a paragraph, even on dialogue-heavy pages where most
    # gaps are the larger between-paragraph gap (the median would hide them).
    line_gap = gaps[len(gaps) // 4] if gaps else 20.0
    paragraphs: list[list[str]] = []
    continues_previous = False
    for i, ln in enumerate(lines):
        offset = ln["x"] - margin
        indented = 10 <= offset <= 20
        if i == 0:
            starts = is_chapter_start or indented or offset > 20
            continues_previous = not starts
        else:
            prev = lines[i - 1]
            big_gap = (prev["y"] - ln["y"]) > line_gap * 1.25
            same_block = offset > 20 and abs(prev["x"] - ln["x"]) < 1.0 and not big_gap
            starts = (indented or big_gap or offset > 20) and not same_block
        if starts or not paragraphs:
            paragraphs.append([ln["text"]])
        else:
            paragraphs[-1].append(ln["text"])
    joined = [_join_lines(p) for p in paragraphs]
    log["lines_ending_with_hyphen"] += sum(1 for ln in lines if ln["text"].endswith("-"))
    return joined, continues_previous


def _join_lines(parts: list[str]) -> str:
    """Join visual lines with a space, except after a line-final hyphen: this edition
    does not hyphenate words, so 'emerald-' + 'green' is the compound 'emerald-green'."""
    out = parts[0]
    for part in parts[1:]:
        hyphen = out.endswith("-") and not out.endswith(" -")
        out += part if hyphen else " " + part
    return normalize_text(out)


# --------------------------------------------------------------- loading -----
def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def load_pdf(path: Path, document_id: str, source: str, books: list[int],
             cache_dir: Path) -> tuple[list[DocumentPage], dict[str, Any]]:
    """Extract every chapter page of the selected books; cache the result.

    Title, contents and copyright pages are excluded (not counted as content).
    Pages without extractable text are logged, never silently dropped.
    """
    if not path.exists():
        raise FileNotFoundError(f"Corpus PDF not found: {path}. Put harrypotter.pdf in "
                                f"starter/data/raw/ or set CORPUS_PDF in starter/.env")
    pdf_hash = sha256_file(path)
    cache_file = cache_dir / "pages.jsonl"
    meta_file = cache_dir / "pages_meta.json"
    cache_key = {"pdf_sha256": pdf_hash, "books": books, "ingestion_version": INGESTION_VERSION}
    if cache_file.exists() and meta_file.exists():
        meta = json.loads(meta_file.read_text(encoding="utf-8"))
        if meta.get("cache_key") == cache_key:
            pages = [DocumentPage(**json.loads(line))
                     for line in cache_file.read_text(encoding="utf-8").splitlines()]
            return pages, meta["log"]

    started = time.perf_counter()
    reader = pypdf.PdfReader(str(path))
    chapters = [c for c in read_outline(reader) if c["book_no"] in books]
    log: dict[str, Any] = {
        "pdf_sha256": pdf_hash, "physical_pages_in_pdf": len(reader.pages),
        "books": books, "empty_pages": [], "drop_caps_joined": [],
        "chapter_start_without_drop_cap": [], "heading_lines_removed": 0,
        "page_number_lines_removed": 0, "lines_ending_with_hyphen": 0, "errors": [],
        "pages_with_unusual_margin": [],
    }
    pages: list[DocumentPage] = []
    for ch in chapters:
        for page_no in range(ch["start"], ch["end"] + 1):
            try:
                lines = _page_lines(reader.pages[page_no - 1])
            except Exception as exc:  # keep going, but record the failure
                log["errors"].append({"page": page_no, "error": repr(exc)})
                continue
            if not lines:
                log["empty_pages"].append(page_no)
                continue
            # Left margin = smallest x on the page. (The most common x is wrong on
            # dialogue-heavy pages, where indented first lines outnumber margin lines.)
            margin = min(round(ln["x"], 1) for ln in lines)
            if abs(margin - 72.0) > 0.5:
                log["pages_with_unusual_margin"].append(page_no)
            paras, cont = _paragraphs(lines, margin, page_no == ch["start"], log, page_no)
            if not paras:
                log["empty_pages"].append(page_no)
                continue
            pages.append(DocumentPage(
                document_id=document_id, source=source, page=page_no, text="\n".join(paras),
                metadata={"book_no": ch["book_no"], "book_title": ch["book_title"],
                          "chapter_no": ch["chapter_no"], "chapter_title": ch["chapter_title"],
                          "continues_previous_page": cont, "paragraphs": len(paras)}))
    log["chapters"] = chapters
    log["extract_seconds"] = round(time.perf_counter() - started, 1)

    cache_dir.mkdir(parents=True, exist_ok=True)
    with cache_file.open("w", encoding="utf-8") as handle:
        for page in pages:
            handle.write(json.dumps(asdict(page), ensure_ascii=False) + "\n")
    meta_file.write_text(json.dumps({"cache_key": cache_key, "log": log}, ensure_ascii=False,
                                    indent=1), encoding="utf-8")
    return pages, log


def build_manifest(pages: list[DocumentPage], log: dict[str, Any], pdf_path: Path,
                   source_id: str) -> dict[str, Any]:
    """Manifest without book text: page IDs, char counts and counting rule."""
    by_book: dict[int, dict[str, Any]] = {}
    for page in pages:
        book = by_book.setdefault(page.metadata["book_no"], {
            "book_no": page.metadata["book_no"], "book_title": page.metadata["book_title"],
            "pages": [], "chars": 0})
        book["pages"].append(page.page)
        book["chars"] += len(page.text)
    books = []
    for book in by_book.values():
        chs = [c for c in log["chapters"] if c["book_no"] == book["book_no"]]
        books.append({**{k: v for k, v in book.items() if k != "pages"},
                      "content_pages_counted": len(book["pages"]),
                      "page_ranges": [[c["start"], c["end"]] for c in chs],
                      "chapters": len(chs)})
    return {
        "source_id": source_id,
        "title": "Harry Potter: The Complete Collection (Pottermore digital edition, calibre PDF)",
        "author": "J.K. Rowling",
        "source_path_or_url": f"local file: {pdf_path.name} (not committed)",
        "sha256": log["pdf_sha256"],
        "license_or_permission": (
            "Copyrighted (c) J.K. Rowling / Pottermore Ltd, all rights reserved. Use as the corpus "
            "for this Day 06 lab was accepted by the instructor (confirmed by the student on "
            "2026-11-14). The acceptance covers processing for the lab, not redistribution: the "
            "raw PDF, extracted text, chunks, vector index and full-text traces stay out of the "
            "repo (.gitignore / Docker volume) and nothing is sent to an external API (local "
            "embedding model). The repo keeps only IDs, metadata, scores and short quotes."),
        "permission_status": "accepted by instructor for the lab (student-confirmed 2026-11-14)",
        "accessed_at": "2026-11-14",
        "snapshot_or_version": "PDF metadata: creator calibre 3.27.1, created 2019-02-21",
        "physical_pages_in_pdf": log["physical_pages_in_pdf"],
        "page_counting_rule": (
            "Count only physical PDF pages inside a chapter range taken from the PDF outline "
            "(Chapter N start page .. next outline entry - 1). Title pages, contents, "
            "'Pottermore.com' and copyright pages are excluded. Pages with no extractable "
            "text are listed in empty_pages and not counted."),
        "books_included": books,
        "content_pages_counted": len(pages),
        "total_chars_normalized": sum(len(p.text) for p in pages),
        "empty_pages": log["empty_pages"],
        "extraction_errors": log["errors"],
        "tools": {"pdf_reader": f"pypdf {pypdf.__version__}", "ocr": "not needed (text PDF)"},
        "page_list_columns": ["page", "book_no", "chapter_no", "chars_normalized"],
        "page_list": [[p.page, p.metadata["book_no"], p.metadata["chapter_no"], len(p.text)] for p in pages],
    }
