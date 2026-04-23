"""Generate completion proposals from gaps using RAG evidence + qwen."""
from __future__ import annotations

import json
import logging
from pathlib import Path

from config import COMPLETION_DIR, ONTOLOGY_PATH, RAG_TOP_K
from utils import call_llm_json, cosine, embed

log = logging.getLogger(__name__)


def _load_records(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("records", [])


def _retrieve(records: list[dict], query: str, top_k: int) -> list[dict]:
    qv = embed(query)
    scored = []
    for r in records:
        score = cosine(qv, r.get("embedding", []))
        scored.append((score, r))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [r for s, r in scored[:top_k] if s > 0]


def _prompt_for_gap(gap: dict, evidence: list[dict], ontology_hint: str) -> str:
    evidence_text = "\n\n".join(
        [
            f"EVIDENCE {i+1} ({e['file']}#{e['chunk_index']}): {e['text'][:700]}"
            for i, e in enumerate(evidence)
        ]
    )
    return (
        "You complete a transport KG. Return ONLY JSON object with key 'proposals'. "
        "Each proposal must include subject, predicate, object, confidence (0-1), rationale, evidence_ids. "
        "Do not invent unsupported facts. If no safe fact, return {'proposals': []}.\n\n"
        f"Gap: {json.dumps(gap, ensure_ascii=True)}\n"
        f"Ontology hints:\n{ontology_hint}\n\n"
        f"{evidence_text}\n"
    )


def run() -> Path:
    COMPLETION_DIR.mkdir(parents=True, exist_ok=True)
    gaps_path = COMPLETION_DIR / "gaps.json"
    index_path = COMPLETION_DIR / "rag_index.json"
    out = COMPLETION_DIR / "proposals.json"

    gaps = json.loads(gaps_path.read_text(encoding="utf-8")).get("gaps", [])
    records = _load_records(index_path)
    ontology_hint = ONTOLOGY_PATH.read_text(encoding="utf-8", errors="ignore")[:8000] if ONTOLOGY_PATH.exists() else ""

    all_props = []
    for gap in gaps:
        q = f"{gap.get('gap_type','')} {gap.get('label','')} {gap.get('subject','')}"
        ev = _retrieve(records, q, RAG_TOP_K)
        prompt = _prompt_for_gap(gap, ev, ontology_hint)
        resp = call_llm_json(prompt)
        props = resp.get("proposals", []) if isinstance(resp, dict) else []
        if not isinstance(props, list):
            props = []

        for p in props:
            p["gap_type"] = gap.get("gap_type")
            p["gap_kind"] = gap.get("kind")
            p["target_subject"] = gap.get("subject")
            if "subject" not in p or not p.get("subject"):
                p["subject"] = gap.get("subject")
        all_props.extend(props)

    payload = {"count": len(all_props), "proposals": all_props}
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    log.info("Proposal generation complete: %d proposal(s) -> %s", len(all_props), out)
    return out


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    run()
