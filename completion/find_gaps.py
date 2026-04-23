"""Detect graph incompleteness with fixed SPARQL checks."""
from __future__ import annotations

import json
import logging
from pathlib import Path

from rdflib import ConjunctiveGraph

from config import COMPLETION_DIR, KG_INPUT_PATH
from utils import sparql_rows

log = logging.getLogger(__name__)


def _load_graph(path: Path) -> ConjunctiveGraph:
    g = ConjunctiveGraph()
    fmt = "turtle" if path.suffix.lower() in {".ttl", ".n3"} else "xml"
    g.parse(str(path), format=fmt)
    return g


def run() -> Path:
    COMPLETION_DIR.mkdir(parents=True, exist_ok=True)
    out = COMPLETION_DIR / "gaps.json"

    g = _load_graph(KG_INPUT_PATH)
    gaps = []

    # Instance gaps
    rows = sparql_rows(
        g,
        """
        SELECT ?i ?lbl WHERE {
          ?i a owl:NamedIndividual .
          OPTIONAL { ?i rdfs:label ?lbl }
          FILTER NOT EXISTS { ?i a ?t . FILTER(?t != owl:NamedIndividual) }
        }
        LIMIT 120
        """,
    )
    for r in rows:
        gaps.append(
            {
                "kind": "instance",
                "gap_type": "missing_specific_type",
                "subject": r.get("i"),
                "label": r.get("lbl", ""),
                "target_predicate": "rdf:type",
            }
        )

    rows = sparql_rows(
        g,
        """
        SELECT ?s ?lbl WHERE {
          ?s a :Station .
          OPTIONAL { ?s rdfs:label ?lbl }
          FILTER NOT EXISTS { ?s :hasZone ?z }
        }
        LIMIT 120
        """,
    )
    for r in rows:
        gaps.append(
            {
                "kind": "instance",
                "gap_type": "station_missing_zone",
                "subject": r.get("s"),
                "label": r.get("lbl", ""),
                "target_predicate": "http://example.org/tfl#hasZone",
            }
        )

    rows = sparql_rows(
        g,
        """
        SELECT ?line ?lbl WHERE {
          ?line a :Line .
          OPTIONAL { ?line rdfs:label ?lbl }
          FILTER NOT EXISTS { ?line :hasTransportMode ?m }
        }
        LIMIT 120
        """,
    )
    for r in rows:
        gaps.append(
            {
                "kind": "instance",
                "gap_type": "line_missing_mode",
                "subject": r.get("line"),
                "label": r.get("lbl", ""),
                "target_predicate": "http://example.org/tfl#hasTransportMode",
            }
        )

    # Ontology-ish coverage gaps (class exists but no/low instances)
    rows = sparql_rows(
        g,
        """
        SELECT ?c ?lbl (COUNT(?i) AS ?n) WHERE {
          ?c a owl:Class ; rdfs:label ?lbl .
          OPTIONAL { ?i a ?c }
        }
        GROUP BY ?c ?lbl
        HAVING (COUNT(?i) < 1)
        LIMIT 200
        """,
    )
    for r in rows:
        gaps.append(
            {
                "kind": "ontology",
                "gap_type": "class_without_instances",
                "subject": r.get("c"),
                "label": r.get("lbl", ""),
                "target_predicate": "rdf:type",
            }
        )

    out.write_text(json.dumps({"input_graph": str(KG_INPUT_PATH), "gaps": gaps}, indent=2), encoding="utf-8")
    log.info("Gap detection complete: %d gap(s) -> %s", len(gaps), out)
    return out


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    run()
