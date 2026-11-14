"""Second, independent metadata check for results/audit/metadata_check.csv.

Unlike the pipeline's auto_* columns (which compare against the pipeline's own normalized
page cache), this re-reads the ORIGINAL PDF with plain `pypdf.extract_text()` and the PDF
outline, then fills manual_ok / note / checked_by. Whitespace is ignored when matching so
line breaks, tabs and the pipeline's hyphen joining cannot cause false mismatches.

    cd starter && python scripts/verify_metadata_raw.py
"""
import csv
import json
import re
import sys
import unicodedata
from pathlib import Path

import pypdf

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src import config  # noqa: E402
from src.ingestion import read_outline  # noqa: E402

CHECKER = "claude: verify_metadata_raw.py (raw pypdf text + PDF outline)"
TR = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "—": "-", "–": "-"})


def squash(text: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text).translate(TR).lower())


def main() -> None:
    sheet = config.RESULTS_DIR / "audit" / "metadata_check.csv"
    traces = config.PRIVATE_RESULTS_DIR / "traces_full.jsonl"
    text_by_id = {h["chunk_id"]: h["text"] for line in traces.read_text(encoding="utf-8").splitlines()
                  for h in json.loads(line)["hits"]}
    reader = pypdf.PdfReader(str(config.CORPUS_PDF))
    chapters = read_outline(reader)
    cache: dict[int, str] = {}

    def raw(page: int) -> str:
        if page not in cache:
            cache[page] = squash(reader.pages[page - 1].extract_text() or "") if 1 <= page <= len(reader.pages) else ""
        return cache[page]

    rows = list(csv.DictReader(sheet.open(encoding="utf-8-sig", newline="")))
    for r in rows:
        if r["manual_ok"].strip() and r.get("checked_by", "") not in ("", CHECKER):
            continue  # keep a human check
        page, page_end = int(r["page"]), int(r["page_end"])
        words = text_by_id[r["chunk_id"]].split()
        head, tail = squash(" ".join(words[:8])), squash(" ".join(words[-8:]))
        p0 = raw(page)
        i = (p0 + raw(page + 1)).find(head)
        if i < 0:  # chapter opening: drop-cap letter is a separate glyph in the raw text
            i = (p0 + raw(page + 1)).find(head[1:])
        before = raw(page_end - 1)
        j = (before + raw(page_end)).find(tail)
        head_ok = 0 <= i < len(p0)
        tail_ok = j >= 0 and j + len(tail) > len(before)
        ch = next((c for c in chapters if c["start"] <= page <= c["end"]), None)
        outline_ok = bool(ch and ch["book_no"] == int(r["book_no"]) and ch["chapter_no"] == int(r["chapter_no"]))
        source_ok = r["source"] == config.SOURCE_NAME
        problems = [name for name, ok in (("start not on page", head_ok), ("end not on page_end", tail_ok),
                                          ("book/chapter mismatch", outline_ok), ("source", source_ok)) if not ok]
        r["manual_ok"] = "0" if problems else "1"
        r["note"] = "; ".join(problems) if problems else (
            f"raw PDF: starts p{page}, ends p{page_end}; outline = book {ch['book_no']} ch {ch['chapter_no']}")
        r["checked_by"] = CHECKER
    with sheet.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    ok = sum(r["manual_ok"] == "1" for r in rows)
    print(f"{ok}/{len(rows)} records confirmed against the raw PDF")
    for r in rows:
        if r["manual_ok"] != "1":
            print("  FAIL", r["question_id"], r["strategy"], r["rank"], r["chunk_id"], r["note"])


if __name__ == "__main__":
    main()
