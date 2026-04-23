"""Validate and apply completion proposals to produce final_completed.ttl."""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from rdflib import ConjunctiveGraph, OWL, RDF, RDFS, URIRef

from config import COMPLETION_DIR, KG_INPUT_PATH, KG_OUTPUT_PATH
from utils import PREFIXES, to_jsonable_node, to_node

log = logging.getLogger(__name__)


def _load_graph(path: Path) -> ConjunctiveGraph:
    g = ConjunctiveGraph()
    fmt = "turtle" if path.suffix.lower() in {".ttl", ".n3"} else "xml"
    g.parse(str(path), format=fmt)
    return g


def _allowed_predicates(g: ConjunctiveGraph) -> set[str]:
    preds = set()
    query = PREFIXES + """
    SELECT DISTINCT ?p WHERE {
      { ?p a owl:ObjectProperty } UNION { ?p a owl:DatatypeProperty }
    }
    """
    for row in g.query(query):
        preds.add(str(row[0]))
    return preds


def run() -> tuple[Path, Path]:
    COMPLETION_DIR.mkdir(parents=True, exist_ok=True)
    proposals_path = COMPLETION_DIR / "proposals.json"
    report_path = COMPLETION_DIR / "completion_report.json"

    started = time.time()
    g = _load_graph(KG_INPUT_PATH)
    allowed = _allowed_predicates(g)
    proposals = json.loads(proposals_path.read_text(encoding="utf-8")).get("proposals", [])
    total_props = len(proposals)
    log.info("Apply stage: loaded %d proposal(s), %d allowed predicate(s)", total_props, len(allowed))

    accepted = []
    rejected = []
    for idx, p in enumerate(proposals, start=1):
        subj = p.get("subject", "")
        pred = p.get("predicate", "")
        obj = p.get("object", "")
        conf = float(p.get("confidence", 0))

        if not subj or not pred or obj in (None, ""):
            rejected.append({"proposal": p, "reason": "missing_field"})
            continue
        if conf < 0.6:
            rejected.append({"proposal": p, "reason": "low_confidence"})
            continue
        if pred not in allowed:
            rejected.append({"proposal": p, "reason": "predicate_not_in_ontology"})
            continue

        s = URIRef(subj)
        pr = URIRef(pred)
        o = to_node(str(obj))
        g.add((s, pr, o))
        accepted.append(
            {
                "subject": subj,
                "predicate": pred,
                "object": to_jsonable_node(o),
                "confidence": conf,
                "evidence_ids": p.get("evidence_ids", []),
                "rationale": p.get("rationale", ""),
                "gap_type": p.get("gap_type", ""),
                "gap_kind": p.get("gap_kind", ""),
            }
        )

        if idx % 25 == 0 or idx == total_props:
            log.info(
                "Apply stage progress: %d/%d processed (accepted=%d rejected=%d)",
                idx,
                total_props,
                len(accepted),
                len(rejected),
            )

    KG_OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    g.serialize(destination=str(KG_OUTPUT_PATH), format="turtle")

    report = {
        "input_graph": str(KG_INPUT_PATH),
        "output_graph": str(KG_OUTPUT_PATH),
        "accepted_count": len(accepted),
        "rejected_count": len(rejected),
        "accepted": accepted,
        "rejected": rejected,
    }
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    log.info(
        "Apply complete: accepted=%d rejected=%d output=%s (%.2fs)",
        len(accepted),
        len(rejected),
        KG_OUTPUT_PATH,
        time.time() - started,
    )
    return KG_OUTPUT_PATH, report_path


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    run()
