"""Per-type correctness scorer for KG eval answers."""
from __future__ import annotations

import re
from typing import Any


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.lower().strip())


def _extract_int(s: str) -> int | None:
    m = re.search(r"\b(\d+)\b", s)
    return int(m.group(1)) if m else None


def _score_string(expected: str, answer: str) -> tuple[bool, str]:
    ok = _norm(expected) in _norm(answer)
    return ok, f"substring '{expected}' {'found' if ok else 'not found'} in answer"


def _score_set(expected: str, answer: str, threshold: float = 0.5) -> tuple[bool, str]:
    terms = [t.strip() for t in expected.split(",") if t.strip()]
    if not terms:
        return False, "empty expected set"
    norm_ans = _norm(answer)
    matched = [t for t in terms if _norm(t) in norm_ans]
    ratio = len(matched) / len(terms)
    ok = ratio >= threshold
    return ok, f"{len(matched)}/{len(terms)} terms matched ({ratio:.0%}): {matched}"


def _score_count(expected_sparql: str, answer: str) -> tuple[bool, str]:
    from tools import sparql_query

    rows = sparql_query(expected_sparql)
    if not rows or "error" in rows[0]:
        return False, f"SPARQL error: {rows}"
    gt = None
    for val in rows[0].values():
        n = _extract_int(str(val))
        if n is not None:
            gt = n
            break
    if gt is None:
        return False, "could not extract ground-truth count from SPARQL result"
    ans_n = _extract_int(answer)
    if ans_n is None:
        return False, f"no integer found in answer; expected {gt}"
    ok = ans_n == gt
    return ok, f"answer={ans_n}, expected={gt}"


def _score_relation(expected: str, answer: str) -> tuple[bool, str]:
    variants = [v.strip() for v in expected.split("|")]
    norm_ans = _norm(answer)
    matched = [v for v in variants if _norm(v) in norm_ans]
    ok = bool(matched)
    return ok, f"relation variants found: {matched}" if ok else f"none of {variants} in answer"


def score(question: dict[str, Any], answer: str | None) -> dict[str, Any]:
    """Score one question. Returns {correct: bool, detail: str}."""
    if not answer:
        return {"correct": False, "detail": "no answer produced"}

    qtype = question.get("expected_type", "string")
    expected = question.get("expected", "")

    if qtype == "string":
        ok, detail = _score_string(expected, answer)
    elif qtype == "set":
        ok, detail = _score_set(expected, answer)
    elif qtype == "count":
        sparql = question.get("expected_sparql", "")
        ok, detail = _score_count(sparql, answer)
    elif qtype == "relation":
        ok, detail = _score_relation(expected, answer)
    else:
        ok, detail = _score_string(expected, answer)

    return {"correct": ok, "detail": detail}


def summarise(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate results into overall + per-type scores."""
    total = len(results)
    correct = sum(1 for r in results if r.get("correct"))

    by_type: dict[str, list[bool]] = {}
    for r in results:
        t = r.get("expected_type", "string")
        by_type.setdefault(t, []).append(bool(r.get("correct")))

    return {
        "score": f"{correct}/{total}",
        "accuracy": round(correct / total, 3) if total else 0.0,
        "by_type": {
            t: f"{sum(v)}/{len(v)}" for t, v in by_type.items()
        },
    }
