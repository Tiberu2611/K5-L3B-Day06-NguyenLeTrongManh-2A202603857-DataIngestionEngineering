"""Read and normalise source PDFs page by page, keeping page number and source."""
import re
import unicodedata
from pathlib import Path

from pypdf import PdfReader

from .models import DocumentPage

_TRANSLATE = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"',
                            "­": None, " ": " "})
# "CHAPTER ONE" / "Chapter 12" alone on a line.
CHAPTER_LINE = re.compile(r"^\s*chapter\s+([\w-]+)\s*$", re.IGNORECASE | re.MULTILINE)
_NUMBER_WORDS = {w: i for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen "
    "sixteen seventeen eighteen nineteen twenty twenty-one twenty-two twenty-three twenty-four "
    "twenty-five twenty-six twenty-seven twenty-eight twenty-nine thirty thirty-one thirty-two "
    "thirty-three thirty-four thirty-five thirty-six thirty-seven".split())}


def normalize_text(text: str) -> str:
    """NFKC (fixes PDF ligatures), ASCII quotes, re-join hyphenated line breaks,
    one space inside a paragraph, and "\n\n" between paragraphs."""
    text = unicodedata.normalize("NFKC", text).translate(_TRANSLATE)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"(?<=[a-z])-\n(?=[a-z])", "", text)          # hyphenation at line end
    paragraphs = re.split(r"\n\s*\n", text)                      # blank line = paragraph break
    cleaned = [re.sub(r"\s+", " ", p).strip() for p in paragraphs]
    return "\n\n".join(p for p in cleaned if p)


def chapter_number(token: str) -> int | None:
    token = token.lower()
    return int(token) if token.isdigit() else _NUMBER_WORDS.get(token)


def load_pdf(path: Path, document_id: str, source: str, metadata: dict | None = None
             ) -> tuple[list[DocumentPage], list[dict]]:
    """Return (pages, issues). Every physical page is returned with its 1-based
    number; pages with no extractable text are logged in ``issues`` (OCR would be
    a separate step)."""
    reader = PdfReader(str(path))
    pages, issues = [], []
    for index, pdf_page in enumerate(reader.pages, start=1):
        try:
            raw = pdf_page.extract_text() or ""
        except Exception as error:  # keep going, but record the failure
            raw = ""
            issues.append({"document_id": document_id, "page": index, "issue": f"extract_error: {error}"})
        text = normalize_text(raw)
        if not text:
            issues.append({"document_id": document_id, "page": index, "issue": "no_text"})
        pages.append(DocumentPage(document_id=document_id, source=source, page=index, text=text,
                                  metadata=dict(metadata or {})))
    return pages, issues


def tag_chapters(pages: list[DocumentPage]) -> None:
    """Carry the current chapter forward across pages (metadata 'chapter')."""
    current = None
    for page in pages:
        match = CHAPTER_LINE.search(page.text.replace("\n\n", "\n"))
        if match and chapter_number(match.group(1)) is not None:
            current = chapter_number(match.group(1))
        page.metadata["chapter"] = current
