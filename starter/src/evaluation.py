"""Evaluate retrieved evidence and preserve per-query traces.

A retrieved chunk is a *hit* when it comes from a gold source/page AND contains
the whole gold evidence quote (after the same light normalisation on both
sides). Alternative gold evidence listed in the benchmark is accepted too.
Coherence and grounding are NOT inferred here: they are labelled by a human.
"""
import re
import unicodedata
from collections import defaultdict
from typing import Any

EXCERPT_CHARS = 200  # traces keep short excerpts only (copyrighted corpus)

_TRANSLATE = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"',
                            "–": "-", "—": "-", "…": "...", "­": None})


def match_key(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).translate(_TRANSLATE).casefold()
    return re.sub(r"\s+", " ", text).strip()


def gold_items(question: dict[str, Any]) -> list[dict[str, Any]]:
    """Primary gold plus any documented alternatives."""
    items = [{"source_id": question["gold_source_id"], "page": int(question["gold_page"]),
              "evidence_quote": question["evidence_quote"]}]
    for alt in question.get("alternatives", []):
        items.append({"source_id": alt["source_id"], "page": int(alt["page"]),
                      "evidence_quote": alt["evidence_quote"]})
    return items


def _judge(hit: dict[str, Any], golds: list[dict[str, Any]]) -> tuple[bool, bool]:
    """(evidence_hit, page_hit) for one retrieved chunk."""
    page_hit = evidence_hit = False
    chunk_key = match_key(hit["text"])
    for gold in golds:
        if hit["document_id"] == gold["source_id"] and int(hit["page"]) == gold["page"]:
            page_hit = True
            if match_key(gold["evidence_quote"]) in chunk_key:
                evidence_hit = True
    return evidence_hit, page_hit


def _complies(hit: dict[str, Any], filters: dict[str, Any] | None) -> bool:
    for key, value in (filters or {}).items():
        allowed = value if isinstance(value, list) else [value]
        if hit.get(key) not in allowed:
            return False
    return True


def evaluate_query(question: dict[str, Any], hits: list[dict[str, Any]],
                   strategy: str = "", applied_filter: dict[str, Any] | None = None) -> dict[str, Any]:
    golds = gold_items(question)
    rows = []
    for rank, hit in enumerate(hits, start=1):
        evidence_hit, page_hit = _judge(hit, golds)
        rows.append({
            "rank": rank, "chunk_id": hit["chunk_id"], "score": round(hit["score"], 4),
            "document_id": hit["document_id"], "source": hit["source"], "page": hit["page"],
            "book": hit.get("book"), "chapter": hit.get("chapter"),
            "n_chars": len(hit["text"]), "excerpt": hit["text"][:EXCERPT_CHARS],
            "evidence_hit": evidence_hit, "page_hit": page_hit,
        })
    question_filter = question.get("filter") or None
    return {
        "strategy": strategy, "id": question["id"], "split": question["split"],
        "type": question.get("type", ""), "question": question["question"],
        "expected_answer": question["expected_answer"], "gold": golds,
        "question_filter": question_filter, "applied_filter": applied_filter,
        "hit_at_1": bool(rows and rows[0]["evidence_hit"]),
        "hit_at_3": any(r["evidence_hit"] for r in rows[:3]),
        "page_hit_at_3": any(r["page_hit"] for r in rows[:3]),
        "filter_compliant": all(_complies(h, question_filter) for h in hits[:3]) if question_filter else None,
        "hits": rows,
    }


def summarize(traces: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for trace in traces:
        groups[(trace["strategy"], trace["split"])].append(trace)
        groups[(trace["strategy"], "all")].append(trace)
    summary = []
    for (strategy, split), items in sorted(groups.items()):
        n = len(items)
        with_filter = [t for t in items if t["question_filter"]]
        summary.append({
            "strategy": strategy, "split": split, "n": n,
            "hit1": sum(t["hit_at_1"] for t in items),
            "hit3": sum(t["hit_at_3"] for t in items),
            "page_hit3": sum(t["page_hit_at_3"] for t in items),
            "filter_questions": len(with_filter),
            "filter_compliant": sum(bool(t["filter_compliant"]) for t in with_filter),
        })
    return summary
