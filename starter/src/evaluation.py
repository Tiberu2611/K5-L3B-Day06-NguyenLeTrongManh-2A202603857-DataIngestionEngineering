"""Automatic retrieval metrics + per-query traces.

A retrieved chunk is an *evidence hit* when it comes from the gold source, its page
range [page, page_end] contains a gold page, and it contains the FULL gold evidence
quote (after light normalization). Any documented alternative evidence counts.
Coherence and grounding are NOT inferred here: they are labelled by a human.
"""
from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from typing import Any

_TRANSLATE = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"',
                            "—": "-", "–": "-", "…": "..."})


def norm_match(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).translate(_TRANSLATE).lower()
    return re.sub(r"\s+", " ", text).strip()


def gold_evidence(question: dict[str, Any]) -> list[dict[str, Any]]:
    pages = question["gold_page"] if isinstance(question["gold_page"], list) else [question["gold_page"]]
    items = [{"source_id": question["gold_source_id"], "pages": pages, "quote": question["evidence_quote"]}]
    for alt in question.get("alt_evidence", []):
        alt_pages = alt["page"] if isinstance(alt["page"], list) else [alt["page"]]
        items.append({"source_id": alt.get("source_id", question["gold_source_id"]),
                      "pages": alt_pages, "quote": alt["quote"]})
    return items


def _hit_status(hit: dict[str, Any], evidence: list[dict[str, Any]]) -> dict[str, Any]:
    meta = hit["metadata"]
    page_range = range(int(meta["page"]), int(meta.get("page_end", meta["page"])) + 1)
    text = norm_match(hit["text"])
    status = {"source_ok": False, "page_ok": False, "evidence_ok": False, "evidence_partial": False}
    for ev in evidence:
        source_ok = meta.get("document_id") == ev["source_id"]
        page_ok = source_ok and any(p in page_range for p in ev["pages"])
        quote = norm_match(ev["quote"])
        full = quote in text
        words = quote.split()
        head, tail = " ".join(words[: max(3, len(words) // 3)]), " ".join(words[-max(3, len(words) // 3):])
        partial = not full and (head in text or tail in text)
        status["source_ok"] |= source_ok
        status["page_ok"] |= page_ok
        status["evidence_ok"] |= page_ok and full
        status["evidence_partial"] |= page_ok and partial
    status["hit"] = status["evidence_ok"]
    return status


def filter_compliant(hits: list[dict[str, Any]], requested: dict[str, Any] | None) -> bool | None:
    if not requested:
        return None
    return all(all(h["metadata"].get(k) == v for k, v in requested.items()) for h in hits)


def evaluate_query(question: dict[str, Any], hits: list[dict[str, Any]],
                   applied_filter: dict[str, Any] | None) -> dict[str, Any]:
    evidence = gold_evidence(question)
    statuses = [_hit_status(h, evidence) for h in hits]
    any_partial = any(s["evidence_partial"] for s in statuses)
    hit3 = any(s["hit"] for s in statuses)
    if hit3:
        failure = None
    elif any_partial:
        failure = "evidence_split_across_chunks"
    elif any(s["page_ok"] for s in statuses):
        failure = "right_page_but_evidence_missing"
    else:
        failure = "wrong_location"
    return {
        "question_id": question["id"], "split": question["split"], "type": question.get("type"),
        "question": question["question"], "expected_answer": question["expected_answer"],
        "gold_source_id": question["gold_source_id"], "gold_page": question["gold_page"],
        "evidence_quote": question["evidence_quote"],
        "question_filter": question.get("filter"), "applied_filter": applied_filter,
        "hit@1": bool(statuses and statuses[0]["hit"]), "hit@3": hit3,
        "first_hit_rank": next((i + 1 for i, s in enumerate(statuses) if s["hit"]), None),
        "failure_type": failure,
        "filter_compliant": filter_compliant(hits, question.get("filter")),
        "hits": [{**h, "status": s} for h, s in zip(hits, statuses)],
    }


def summarize(traces: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for t in traces:
        groups[(t["strategy"], t["split"])].append(t)
        groups[(t["strategy"], "all")].append(t)
    rows = []
    for (strategy, split), items in sorted(groups.items()):
        n = len(items)
        h1 = sum(t["hit@1"] for t in items)
        h3 = sum(t["hit@3"] for t in items)
        filt = [t for t in items if t["question_filter"]]
        comp = sum(bool(t["filter_compliant"]) for t in filt)
        mrr = sum(1 / t["first_hit_rank"] for t in items if t["first_hit_rank"]) / n
        rows.append({"strategy": strategy, "split": split, "n": n,
                     "hit@1": h1, "hit@1_rate": round(h1 / n, 3),
                     "hit@3": h3, "hit@3_rate": round(h3 / n, 3), "mrr@3": round(mrr, 3),
                     "filter_questions": len(filt),
                     "filter_compliant": comp if filt else None,
                     "failures": {f: sum(t["failure_type"] == f for t in items)
                                  for f in sorted({t["failure_type"] for t in items if t["failure_type"]})}})
    return rows
