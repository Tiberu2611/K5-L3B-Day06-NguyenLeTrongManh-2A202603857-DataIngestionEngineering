"""Day 06 pipeline entry point.

    python -m src.run                 # all stages
    python -m src.run --stage ingest  # ingest | index | eval | audit | audit-summary

Outputs that contain book text go to gitignored folders (data/processed,
data/index, results/private). Committed outputs keep IDs, metadata, scores and
short snippets only.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import platform
import re
import statistics
import sys
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import config
from .chunking import build_chunks, build_streams
from .evaluation import evaluate_query, norm_match, summarize
from .ingestion import build_manifest, load_pdf
from .models import Chunk, DocumentPage


# ----------------------------------------------------------------- helpers ---
def _dump(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def _jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _snippet(text: str, n: int = config.TRACE_SNIPPET_CHARS) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[:n].rsplit(" ", 1)[0] + " …"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _chunk_file(strategy: str) -> Path:
    return config.PROCESSED_DIR / f"chunks_{strategy}.jsonl"


def _load_chunks(strategy: str) -> list[Chunk]:
    return [Chunk(**json.loads(line)) for line in
            _chunk_file(strategy).read_text(encoding="utf-8").splitlines()]


# ------------------------------------------------------------------ stages ---
def stage_ingest() -> list[DocumentPage]:
    pages, log = load_pdf(config.CORPUS_PDF, config.SOURCE_ID, config.SOURCE_NAME,
                          config.BOOKS, config.PROCESSED_DIR)
    if len(pages) < 30:
        raise SystemExit(f"Only {len(pages)} content pages; the lab requires >= 30.")
    if config.MANIFEST_FILE.exists():  # warn if this is not the PDF the recorded results came from
        recorded = json.loads(config.MANIFEST_FILE.read_text(encoding="utf-8")).get("sha256")
        if recorded and recorded != log["pdf_sha256"]:
            print(f"[ingest] WARNING: PDF sha256 {log['pdf_sha256'][:12]} differs from the manifest "
                  f"({recorded[:12]}); results will not match the recorded run.")
    manifest = build_manifest(pages, log, config.CORPUS_PDF, config.SOURCE_ID)
    try:
        where = config.CORPUS_PDF.resolve().relative_to(config.REPO_ROOT).as_posix()
    except ValueError:
        where = config.CORPUS_PDF.name
    manifest["source_path_or_url"] = (f"local file: {where} (gitignored, not committed; "
                                      f"verify with the sha256 below)")
    manifest["metadata_schema"] = config.METADATA_SCHEMA
    text = json.dumps(manifest, ensure_ascii=False, indent=1)
    text = re.sub(r"\[\s*(\d+),\s*(\d+),\s*(\d+),\s*(\d+)\s*\]", r"[\1, \2, \3, \4]", text)  # 1 page per line
    config.MANIFEST_FILE.write_text(text, encoding="utf-8")
    paragraphs = [p.metadata["paragraphs"] for p in pages]
    _dump(config.RESULTS_DIR / "ingest_log.json", {
        "content_pages": len(pages), "total_chars": manifest["total_chars_normalized"],
        "chars_per_page": {"min": min(len(p.text) for p in pages),
                           "median": statistics.median(len(p.text) for p in pages),
                           "max": max(len(p.text) for p in pages)},
        "paragraphs_total": sum(paragraphs),
        "pages_continuing_previous_page": sum(p.metadata["continues_previous_page"] for p in pages),
        **{k: v for k, v in log.items() if k != "chapters"},
        "normalization": ["Unicode NFC", "tabs / NBSP / zero-width spaces -> single space",
                          "visual lines -> paragraphs using indent + vertical gap",
                          "chapter headings removed (kept as chapter_title metadata)",
                          "drop-cap first letter re-attached to the first word",
                          "line-final hyphen joined without space (edition does not hyphenate words)",
                          "curly quotes and dashes kept as in source"],
        "known_limitations": [
            "When a chapter opens with dialogue, the drop-cap glyph carries no opening quote, so the "
            "first paragraph loses its opening quotation mark (e.g. p123 'There, look.”').",
            "Hyphen rule assumes no word-splitting hyphenation; a real split word would keep a hyphen.",
            "Run 1 used the most common x as the left margin; on dialogue-heavy pages that merged "
            "separate dialogue paragraphs. Found during the coherence audit (P06, p526); fixed in "
            "ingestion v3 (margin = smallest x, gap threshold from lower quartile). Run 1 results are "
            "kept in results/history/run1_paragraph_bug/.",
            "Pages 106, 111, 352, 866 (short end-of-chapter pages where EVERY line is indented: one-line "
            "dialogue or the Sorting Hat song) have no line at the 72pt margin, so their paragraphs are "
            "merged into one. None is a gold page. Fix for a next run: fall back to the corpus-wide "
            "margin (72pt) when a page's smallest x is larger.",
            "Paragraph detection relies on this PDF's layout (indent 14.4pt); other PDFs need re-checking."]})
    print(f"[ingest] {len(pages)} content pages, {manifest['total_chars_normalized']:,} chars, "
          f"empty={len(log['empty_pages'])}, errors={len(log['errors'])}")
    return pages


def stage_index(pages: list[DocumentPage]) -> None:
    from .embeddings import SentenceTransformerEmbedder
    from .store import make_store

    streams = build_streams(pages)
    t0 = time.perf_counter()
    embedder = SentenceTransformerEmbedder()
    load_s = time.perf_counter() - t0
    store = make_store(embedder.dimensions, embedder.model_name)
    stats: dict[str, Any] = {"embedding": embedder.describe(), "model_load_seconds": round(load_s, 1),
                             "vector_store": store.describe(), "metadata_schema": config.METADATA_SCHEMA,
                             "strategies": {}}
    cache: dict[str, list[float]] = {}  # text sha1 -> vector; C reuses B's vectors (identical chunks)

    def embed_cached(texts: list[str]) -> list[list[float]]:
        keys = [hashlib.sha1(t.encode()).hexdigest() for t in texts]
        missing = [(k, t) for k, t in dict(zip(keys, texts)).items() if k not in cache]
        if missing:
            cache.update(zip([k for k, _ in missing], embedder.embed_documents([t for _, t in missing])))
        return [cache[k] for k in keys]

    for name, params in config.STRATEGIES.items():
        t_chunk = time.perf_counter()
        chunks = build_chunks(streams, name, params)
        chunk_s = time.perf_counter() - t_chunk
        _jsonl(_chunk_file(name), [asdict(c) for c in chunks])
        lengths = [len(c.text) for c in chunks]
        tokens = embedder.count_tokens([c.text for c in chunks])
        t_emb = time.perf_counter()
        cached_before = sum(hashlib.sha1(c.text.encode()).hexdigest() in cache for c in chunks)
        first = store.upsert(params["collection"], chunks, embed_cached)
        emb_s = time.perf_counter() - t_emb
        t_re = time.perf_counter()
        second = store.upsert(params["collection"], chunks, embed_cached)  # re-ingest check
        re_s = time.perf_counter() - t_re
        q = statistics.quantiles(lengths, n=10)
        stats["strategies"][name] = {
            "params": {k: v for k, v in params.items() if k not in ("hypothesis",)},
            "chunks": len(chunks), "cross_page_chunks": sum(c.page != c.metadata["page_end"] for c in chunks),
            "length_chars": {"min": min(lengths), "p10": round(q[0]), "median": statistics.median(lengths),
                             "p90": round(q[-1]), "max": max(lengths), "mean": round(statistics.mean(lengths), 1)},
            "total_chars": sum(lengths), "total_tokens_incl_prefix": sum(tokens),
            "chunks_over_max_seq_len": sum(t > embedder.max_seq_length for t in tokens),
            "chunking_seconds": round(chunk_s, 2), "embed_and_write_seconds": round(emb_s, 1),
            "vectors_reused_from_earlier_strategy": cached_before,
            "first_ingest": first, "reingest_same_version": second,
            "reingest_seconds": round(re_s, 1),
            "reingest_ok": second["embedded_or_updated"] == 0 and second["obsolete_deleted"] == 0
                           and second["count_after"] == len(chunks),
            "cost_usd": 0.0,
        }
        print(f"[index] {name}: {len(chunks)} chunks, embed+write {emb_s:.1f}s, "
              f"reingest -> {second}")
    stats["finished_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    _dump(config.RESULTS_DIR / "index_stats.json", stats)


def verify_benchmark(questions: list[dict], pages: list[DocumentPage]) -> list[dict]:
    """Every evidence quote must exist on its gold page(s) after normalization."""
    page_text = {p.page: p.text for p in pages}
    books = {p.metadata["book_no"] for p in pages}
    report = []
    for q in questions:
        golds = [(q["gold_page"], q["evidence_quote"])] + [(a["page"], a["quote"]) for a in q.get("alt_evidence", [])]
        for gp, quote in golds:
            gps = gp if isinstance(gp, list) else [gp]
            text = " ".join(page_text.get(p, "") for p in gps)
            ok = norm_match(quote) in norm_match(text)
            report.append({"id": q["id"], "pages": gps, "found": ok})
        if q.get("filter"):
            bad = set(q["filter"]) - config.FILTER_FIELDS
            if bad or q["filter"].get("book_no") not in books:
                raise SystemExit(f"{q['id']}: filter {q['filter']} not allowed / value not in corpus")
    missing = [r for r in report if not r["found"]]
    if missing:
        raise SystemExit(f"Evidence not found on gold page: {missing}")
    return report


def stage_eval(pages: list[DocumentPage]) -> None:
    from .embeddings import SentenceTransformerEmbedder
    from .store import make_store

    bench = json.loads(config.BENCHMARK_FILE.read_text(encoding="utf-8"))
    questions = bench["questions"]
    splits = {s: sum(q["split"] == s for q in questions) for s in ("dev", "test")}
    if len(questions) < 20 or splits["dev"] < 15 or splits["test"] < 5:
        raise SystemExit(f"Benchmark too small: {splits}")
    verification = verify_benchmark(questions, pages)

    embedder = SentenceTransformerEmbedder()
    store = make_store(embedder.dimensions, embedder.model_name)
    qvec ={q["id"]: embedder.embed_query(q["question"]) for q in questions}  # same query vector for A/B/C
    traces = []
    for name, params in config.STRATEGIES.items():
        for q in questions:
            applied = q.get("filter") if params["use_filter"] else None
            t0 = time.perf_counter()
            hits = store.search(params["collection"], qvec[q["id"]], config.TOP_K, applied)
            latency_ms = (time.perf_counter() - t0) * 1000
            trace = evaluate_query(q, hits, applied)
            trace.update({"strategy": name, "latency_ms": round(latency_ms, 1)})
            traces.append(trace)
    summary = summarize(traces)
    run_info = {"run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "benchmark_sha256": _sha256(config.BENCHMARK_FILE), "benchmark_frozen_at": bench.get("frozen_at"),
                "python": sys.version.split()[0], "platform": platform.platform(),
                "embedding": embedder.describe(), "vector_store": store.describe(), "top_k": config.TOP_K,
                "evidence_verification": {"checked": len(verification),
                                          "found": sum(r["found"] for r in verification)}}
    _jsonl(config.PRIVATE_RESULTS_DIR / "traces_full.jsonl", traces)
    public = []
    for t in traces:
        t = json.loads(json.dumps(t))
        # Explicit "not applicable" values instead of null in the committed trace.
        t["question_filter"] = t["question_filter"] or "none"
        t["applied_filter"] = t["applied_filter"] or "none"
        t["filter_compliant"] = "N/A" if t["filter_compliant"] is None else t["filter_compliant"]
        t["failure_type"] = t["failure_type"] or "none (hit)"
        t["first_hit_rank"] = t["first_hit_rank"] or "not in top-3"
        for h in t["hits"]:
            h["snippet"] = _snippet(h.pop("text"))
            h["metadata"] = {k: v for k, v in h["metadata"].items() if k not in ("stream_start", "stream_end")}
        public.append(t)
    _jsonl(config.RESULTS_DIR / "traces.jsonl", public)
    _dump(config.RESULTS_DIR / "metrics.json", {"run": run_info, "summary": summary})
    _write_metrics_md(summary, traces, run_info)
    _update_experiment_log(summary)
    for row in summary:
        if row["split"] != "all":
            print(f"[eval] {row['strategy']} {row['split']:4}: Hit@1 {row['hit@1']}/{row['n']}  "
                  f"Hit@3 {row['hit@3']}/{row['n']}  filter {row['filter_compliant']}/{row['filter_questions']}")


def _write_metrics_md(summary: list[dict], traces: list[dict], run_info: dict) -> None:
    stats_file = config.RESULTS_DIR / "index_stats.json"
    stats = json.loads(stats_file.read_text(encoding="utf-8"))["strategies"] if stats_file.exists() else {}
    lines = ["# Retrieval metrics (auto-generated)", "",
             f"Run: {run_info['run_at']} · model `{run_info['embedding']['model']}` · top-{run_info['top_k']} · "
             f"benchmark sha256 `{run_info['benchmark_sha256'][:12]}`", "",
             "| Strategy | Split | Hit@1 (n/N) | Evidence Hit@3 (n/N) | MRR@3 | Filter compliant | Chunks | Embed+write (s) | Cost |",
             "|---|---|---|---|---|---|---|---|---|"]
    for r in summary:
        st = stats.get(r["strategy"], {})
        filt = f"{r['filter_compliant']}/{r['filter_questions']}" if r["filter_questions"] else "N/A"
        lines.append(f"| {r['strategy']} | {r['split']} | {r['hit@1']}/{r['n']} | {r['hit@3']}/{r['n']} | "
                     f"{r['mrr@3']} | {filt} | {st.get('chunks', '?')} | {st.get('embed_and_write_seconds', '?')} | $0 |")
    lines += ["", "## Per-question Hit@3 (1 = evidence hit in top-3)", "",
              "| ID | Split | Type | Filter | A | B | C |", "|---|---|---|---|---|---|---|"]
    by_q: dict[str, dict] = {}
    for t in traces:
        by_q.setdefault(t["question_id"], {"t": t})[t["strategy"]] = t
    for qid, d in by_q.items():
        t = d["t"]
        cell = lambda s: "—" if s not in d else (f"{int(d[s]['hit@3'])} (r{d[s]['first_hit_rank']})"
                                                 if d[s]["hit@3"] else f"0 · {d[s]['failure_type']}")
        lines.append(f"| {qid} | {t['split']} | {t['type']} | {t['question_filter'] or ''} | "
                     f"{cell('A')} | {cell('B')} | {cell('C')} |")
    (config.RESULTS_DIR / "metrics.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _update_experiment_log(summary: list[dict]) -> None:
    get = {(r["strategy"], r["split"]): r for r in summary}
    rows = []
    for name, p in config.STRATEGIES.items():
        fmt = lambda split, k: f"{get[(name, split)][k]}/{get[(name, split)]['n']}" if (name, split) in get else ""
        rows.append({"strategy": name, "chunking": p["chunking"],
                     "chunk_size": p.get("size", p.get("max_size")), "overlap": p.get("overlap", 0),
                     "metadata": "document_id;source;page;page_end;book_no;book_title;chapter_no;chapter_title",
                     "filter": "book_no (only when question supplies it)" if p["use_filter"] else "none",
                     "vectorizer": f"{config.EMBEDDING_MODEL} (local CPU, 384-d, cosine, {config.VECTOR_STORE})",
                     "hypothesis": p["hypothesis"],
                     "dev_hit1": fmt("dev", "hit@1"), "dev_hit3": fmt("dev", "hit@3"),
                     "test_hit1": fmt("test", "hit@1"), "test_hit3": fmt("test", "hit@3"),
                     "notes": "C reuses B chunks/vectors; differs from B only by the filter"
                              if name == "C" else ""})
    with config.EXPERIMENT_LOG.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def stage_audit(pages: list[DocumentPage]) -> None:
    """Build manual-labelling sheets. Sample positions are fixed by rule, not by score."""
    traces_file = config.PRIVATE_RESULTS_DIR / "traces_full.jsonl"
    traces = [json.loads(l) for l in traces_file.read_text(encoding="utf-8").splitlines()]
    audit_dir, private = config.RESULTS_DIR / "audit", config.PRIVATE_RESULTS_DIR
    streams = {(s.metadata["book_no"], s.metadata["chapter_no"]): s for s in build_streams(pages)}

    # 1) Coherence: 10 pages evenly spaced over the sorted content pages; the position is
    #    the midpoint of that page's text inside its chapter stream.
    picks = [pages[round(i * (len(pages) - 1) / 9)] for i in range(10)]
    positions = []
    for i, p in enumerate(picks, 1):
        s = streams[(p.metadata["book_no"], p.metadata["chapter_no"])]
        idx = s.page_numbers.index(p.page)
        start = s.page_starts[idx]
        end = s.page_starts[idx + 1] if idx + 1 < len(s.page_starts) else len(s.text)
        positions.append({"pos_id": f"P{i:02d}", "page": p.page, "book_no": p.metadata["book_no"],
                          "chapter_no": p.metadata["chapter_no"], "offset": (start + end) // 2})
    coh_private, coh_public = [], []
    for name in config.STRATEGIES:
        chunks = _load_chunks(name)
        for pos in positions:
            chunk = next(c for c in chunks if c.metadata["book_no"] == pos["book_no"]
                         and c.metadata["chapter_no"] == pos["chapter_no"]
                         and c.metadata["stream_start"] <= pos["offset"] < c.metadata["stream_end"] + 2)
            base = {"pos_id": pos["pos_id"], "strategy": name, "page": pos["page"], "chunk_id": chunk.chunk_id,
                    "chunk_pages": f"{chunk.page}-{chunk.metadata['page_end']}", "chars": len(chunk.text)}
            coh_private.append({**base, "chunk_text": chunk.text})
            coh_public.append({**base, "starts": _snippet(chunk.text, 60),
                               "ends": "… " + " ".join(chunk.text.split())[-60:], **_LABEL_COLUMNS})
    _csv(private / "audit_coherence_fulltext.csv", coh_private)
    _merge_labels(audit_dir / "coherence_labels.csv", coh_public, ("pos_id", "strategy", "chunk_id"))

    # 2) Grounding: all test questions x strategy, top-3 shown together.
    test = [t for t in traces if t["split"] == "test"]
    g_private, g_public = [], []
    for t in test:
        base = {"question_id": t["question_id"], "strategy": t["strategy"], "question": t["question"],
                "expected_answer": t["expected_answer"], "applied_filter": json.dumps(t["applied_filter"]),
                "auto_hit@3": int(t["hit@3"])}
        g_private.append({**base, **{f"top{h['rank']}": f"[{h['chunk_id']} p{h['metadata']['page']}-"
                                                       f"{h['metadata']['page_end']}] {h['text']}" for h in t["hits"]}})
        g_public.append({**base, "top3_chunk_ids": " | ".join(h["chunk_id"] for h in t["hits"]),
                         **_LABEL_COLUMNS})
    _csv(private / "audit_grounding_fulltext.csv", g_private)
    _merge_labels(audit_dir / "grounding_labels.csv", g_public, ("question_id", "strategy", "top3_chunk_ids"))

    # 3) Metadata: test x top-3 x strategy. Automatic cross-check against the source pages;
    #    a human still confirms (manual_ok) a sample.
    page_by_no = {p.page: p for p in pages}
    m_rows = []
    for t in test:
        for h in t["hits"]:
            m = h["metadata"]
            p0, p1 = page_by_no.get(m["page"]), page_by_no.get(m["page_end"])
            words = h["text"].split()
            head, tail = norm_match(" ".join(words[:8])), norm_match(" ".join(words[-8:]))
            page_ok = False
            if p0 and p1:
                # The first/last words may straddle a page break: search two adjacent pages but
                # require the head to START on `page` and the tail to END on `page_end`.
                t0, nxt = norm_match(p0.text), page_by_no.get(m["page"] + 1)
                i = (t0 + " " + norm_match(nxt.text if nxt else "")).find(head)
                prv, t1 = page_by_no.get(m["page_end"] - 1), norm_match(p1.text)
                before = norm_match(prv.text) + " " if prv else ""
                j = (before + t1).find(tail)
                page_ok = 0 <= i < len(t0) and j >= 0 and j + len(tail) > len(before)
            outline_ok = bool(p0 and p0.metadata["book_no"] == m["book_no"]
                              and p0.metadata["chapter_no"] == m["chapter_no"])
            m_rows.append({"question_id": t["question_id"], "strategy": t["strategy"], "rank": h["rank"],
                           "chunk_id": h["chunk_id"], "source": m["source"], "page": m["page"],
                           "page_end": m["page_end"], "book_no": m["book_no"], "chapter_no": m["chapter_no"],
                           "auto_source_ok": int(m["source"] == config.SOURCE_NAME
                                                 and m["document_id"] == config.SOURCE_ID),
                           "auto_page_ok": int(page_ok), "auto_book_chapter_ok": int(outline_ok),
                           "requested_filter": json.dumps(t["question_filter"]),
                           "in_requested_scope": "" if not t["question_filter"] else
                           int(all(m.get(k) == v for k, v in t["question_filter"].items())),
                           "manual_ok": "", "note": "", "checked_by": ""})
    _merge_labels(audit_dir / "metadata_check.csv", m_rows, ("question_id", "strategy", "rank", "chunk_id"),
                  keep=("manual_ok", "note", "checked_by"))
    _write_review_sheet(private / "review_sheet.md", coh_private, g_private,
                        _read_csv(audit_dir / "coherence_labels.csv"), _read_csv(audit_dir / "grounding_labels.csv"))
    print(f"[audit] sheets in {audit_dir.relative_to(config.REPO_ROOT)} (labels) and "
          f"{private.relative_to(config.REPO_ROOT)} (full text, gitignored)")


def _write_review_sheet(path: Path, coherence: list[dict], grounding: list[dict],
                        coh_labels: list[dict], g_labels: list[dict]) -> None:
    """Readable full-text sheet for manual labelling (gitignored: contains book text)."""
    quote = lambda text: "\n".join("> " + line for line in text.splitlines())
    hint = lambda row: (f"\n<details><summary>Nhãn hiện tại (mở sau khi đã tự chấm)</summary>\n\n"
                        f"**{row.get('label_0_1_2') or row.get('claude_suggested_0_1_2') or '—'}** · "
                        f"{row.get('reason') or row.get('claude_reason') or '—'} · người chấm: "
                        f"`{row.get('labeled_by') or 'chưa có'}`\n\n</details>\n")
    coh_by = {(r["pos_id"], r["strategy"]): r for r in coh_labels}
    g_by = {(r["question_id"], r["strategy"]): r for r in g_labels}
    out = ["# Phiếu chấm nhãn thủ công (full text, KHÔNG commit)", "",
           "Đọc từng mục, tự quyết định nhãn, rồi điền vào file CSV tương ứng trong `results/audit/`:",
           "cột `label_0_1_2` (0, 1 hoặc 2) và `reason` (một câu lý do). Xong thì chạy",
           "`python -m src.run --stage audit-summary`. Thang điểm và cách chọn mẫu: `results/audit/README.md`.", "",
           "## Phần 1 · Coherence → `coherence_labels.csv`", "",
           "**0** = bị cắt giữa ý / thiếu chủ thể, đọc không hiểu · **1** = hiểu một phần, thiếu ngữ cảnh · "
           "**2** = tự đọc hiểu được, giữ trọn ý", ""]
    for r in coherence:
        out += [f"### {r['pos_id']} · {r['strategy']} · `{r['chunk_id']}` · tr. {r['chunk_pages']} · {r['chars']} ký tự", "",
                quote(r["chunk_text"]), "", f"➡️ Điền dòng `{r['pos_id']},{r['strategy']}`: `label_0_1_2` = ?, `reason` = ?",
                hint(coh_by.get((r["pos_id"], r["strategy"]), {}))]
    out += ["## Phần 2 · Grounding → `grounding_labels.csv`", "",
            "Chấm **cả top-3 gộp lại** cho mỗi câu: **0** = không có bằng chứng · **1** = có nhưng thiếu điều kiện/ngữ cảnh · "
            "**2** = đủ để trả lời và chỉ ra được trang nguồn. Chỉ đánh giá bằng chứng truy xuất, không phải câu trả lời LLM.", ""]
    for r in grounding:
        out += [f"### {r['question_id']} · {r['strategy']} — {r['question']}", "",
                f"- **Đáp án mong đợi:** {r['expected_answer']}",
                f"- **Filter áp dụng:** {r['applied_filter']} · **Hit@3 tự động:** {r['auto_hit@3']}", ""]
        for k in ("top1", "top2", "top3"):
            if r.get(k):
                head, _, body = r[k].partition("] ")
                out += [f"**{k.upper()}** {head}]", "", quote(body), ""]
        out += [f"➡️ Điền dòng `{r['question_id']},{r['strategy']}`: `label_0_1_2` = ?, `reason` = ?",
                hint(g_by.get((r["question_id"], r["strategy"]), {}))]
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


_LABEL_COLUMNS = {"label_0_1_2": "", "reason": "", "labeled_by": "", "claude_suggested_0_1_2": "",
                  "claude_reason": "", "needs_label": ""}


def _merge_labels(path: Path, rows: list[dict], key: tuple[str, ...],
                  keep: tuple[str, ...] = ("label_0_1_2", "reason", "labeled_by",
                                           "claude_suggested_0_1_2", "claude_reason")) -> None:
    """Rewrite a label sheet but carry over labels whose sampled item is unchanged.
    Rows whose chunk / top-3 changed get empty labels and needs_label=1."""
    old = {tuple(r.get(k, "") for k in key): r for r in _read_csv(path)} if path.exists() else {}
    for row in rows:
        prev = old.get(tuple(str(row[k]) for k in key))
        if prev:
            row.update({k: prev.get(k, "") for k in keep})
        if "needs_label" in row:
            row["needs_label"] = "" if (row["label_0_1_2"] or row["claude_suggested_0_1_2"]) else "1"
    _csv(path, rows)


def stage_audit_summary(metrics_file: Path | None = None, out_file: Path | None = None,
                        note: str | None = None) -> None:
    """Final label = label_0_1_2 (fallback: claude_suggested_0_1_2). `labeled_by` records who
    assigned it: 'student…' (student labelled or reviewed) or 'claude-llm-judge'.
    `metrics_file` / `out_file` let an archived run be summarized with the same labels."""
    audit_dir = config.RESULTS_DIR / "audit"
    metrics_file = metrics_file or config.RESULTS_DIR / "metrics.json"
    out_file = out_file or config.RESULTS_DIR / "audit_summary.json"
    out: dict[str, Any] = {"label_policy": (
        "final label = label_0_1_2, falling back to claude_suggested_0_1_2 if empty. labeled_by says "
        "who assigned it: 'claude-llm-judge' = Claude read the full text against the rubric (method in "
        "results/audit/README.md), not reviewed by the student; 'student' = labelled or reviewed and "
        "confirmed by the student (an empty labeled_by on a filled label counts as student). "
        "student_reviewed < n means the result still contains unreviewed LLM-judge labels.")}

    def source(row: dict) -> str:
        if not row["label_0_1_2"].strip():
            return "claude_suggested_only"
        who = row.get("labeled_by", "").strip().lower()
        return "student" if (not who or who.startswith("student")) else who
    for kind in ("coherence", "grounding"):
        rows = _read_csv(audit_dir / f"{kind}_labels.csv")
        missing = [r for r in rows if not (r["label_0_1_2"].strip() or r["claude_suggested_0_1_2"].strip())]
        if missing:
            ids = [f"{r.get('pos_id') or r.get('question_id')}/{r['strategy']}" for r in missing]
            raise SystemExit(f"{kind}: rows without any label (needs_label=1): {ids}")
        for name in config.STRATEGIES:
            rs = [r for r in rows if r["strategy"] == name]
            final = [int(r["label_0_1_2"] if r["label_0_1_2"].strip() else r["claude_suggested_0_1_2"])
                     for r in rs]
            if any(v not in (0, 1, 2) for v in final):
                raise SystemExit(f"{kind}/{name}: labels must be 0, 1 or 2")
            sources = [source(r) for r in rs]
            out.setdefault(kind, {})[name] = {
                "n": len(final), "counts_0_1_2": [final.count(v) for v in (0, 1, 2)],
                "mean_of_2": round(sum(final) / len(final), 2),
                "label_source": {s: sources.count(s) for s in sorted(set(sources))},
                "student_reviewed": f"{sources.count('student')}/{len(rs)}"}
    rows = _read_csv(audit_dir / "metadata_check.csv")
    summary =json.loads(metrics_file.read_text(encoding="utf-8"))["summary"] if metrics_file.exists() else []
    dev = {r["strategy"]: r for r in summary if r["split"] == "dev"}
    for name, params in config.STRATEGIES.items():
        rs = [r for r in rows if r["strategy"] == name]
        checks = ("auto_source_ok", "auto_page_ok", "auto_book_chapter_ok")
        errors = [{"question_id": r["question_id"], "rank": int(r["rank"]), "chunk_id": r["chunk_id"],
                   "failed": [c for c in checks if r[c] != "1"]} for r in rs if any(r[c] != "1" for c in checks)]
        by_q: dict[str, bool] = {}
        for r in rs:
            if r["in_requested_scope"] != "":
                by_q[r["question_id"]] = by_q.get(r["question_id"], True) and r["in_requested_scope"] == "1"
        d = dev.get(name, {})
        out.setdefault("metadata", {})[name] = {
            "records_checked": len(rs),
            "complete_and_correct": f"{len(rs) - len(errors)}/{len(rs)}",
            "check_method": "automatic: source+document_id, chunk text starts on `page` and ends on "
                            "`page_end`, book_no/chapter_no match the PDF outline for that page",
            "errors": errors,
            "second_check": {"reviewed": sum(r["manual_ok"].strip() != "" for r in rs),
                             "confirmed_ok": sum(r["manual_ok"].strip() == "1" for r in rs), "of": len(rs),
                             "checked_by": {who: sum((r.get("checked_by") or "unspecified") == who for r in rs
                                                     if r["manual_ok"].strip())
                                            for who in sorted({r.get("checked_by") or "unspecified"
                                                               for r in rs if r["manual_ok"].strip()})}},
            "filter_applied": params["use_filter"],
            "filter_compliance_test": f"{sum(by_q.values())}/{len(by_q)}",
            "filter_compliance_dev": f"{d.get('filter_compliant', 0)}/{d.get('filter_questions', 0)}"}
    if note:
        out = {"note": note, **out}
    _dump(out_file, out)
    print(json.dumps(out, ensure_ascii=False, indent=1))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--stage", default="all",
                        choices=["all", "ingest", "index", "eval", "audit", "audit-summary"])
    stage = parser.parse_args().stage
    if stage == "audit-summary":
        return stage_audit_summary()
    pages = stage_ingest()
    if stage in ("all", "index"):
        stage_index(pages)
    if stage in ("all", "eval"):
        stage_eval(pages)
    if stage in ("all", "audit"):
        stage_audit(pages)


if __name__ == "__main__":
    main()
