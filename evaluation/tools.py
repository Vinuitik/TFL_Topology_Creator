"""SPARQL + schema tools executed against the pipeline output graph."""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from rdflib import ConjunctiveGraph, OWL, RDF, RDFS

log = logging.getLogger(__name__)

_graph: ConjunctiveGraph | None = None

_ROOT = Path(__file__).parent.parent / "outputs"
_kg_env = os.getenv("KG_TTL_PATH", "").strip()
_CANDIDATES = [
    Path(_kg_env) if _kg_env else None,
    _ROOT / "final_clean.ttl",
    _ROOT / "final.ttl",
    _ROOT / "final.owl",
]

_PREFIXES = """
PREFIX owl:  <http://www.w3.org/2002/07/owl#>
PREFIX rdf:  <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX xsd:  <http://www.w3.org/2001/XMLSchema#>
PREFIX :     <http://example.org/tfl#>
PREFIX ex:   <http://example.org/>
"""


def _load_graph() -> ConjunctiveGraph:
    global _graph
    if _graph is not None:
        return _graph
    for path in _CANDIDATES:
        if path is None or not path.exists():
            continue
        fmt = "turtle" if path.suffix in {".ttl", ".n3"} else "xml"
        g = ConjunctiveGraph()
        g.parse(str(path), format=fmt)
        log.info("Loaded graph from %s (%d triples)", path, len(g))
        _graph = g
        return g
    raise FileNotFoundError(
        f"No graph found. Tried: {[str(p) for p in _CANDIDATES if p]}. "
        "Run the pipeline first or set KG_TTL_PATH."
    )


def sparql_query(query: str) -> list[dict[str, Any]]:
    """Execute a SPARQL SELECT query. Returns list of row dicts."""
    g = _load_graph()
    try:
        results = g.query(_PREFIXES + "\n" + query)
        rows = [{str(var): str(val) for var, val in zip(results.vars, row)} for row in results]
        log.info("SPARQL returned %d rows", len(rows))
        return rows
    except Exception as exc:
        log.warning("SPARQL error: %s", exc)
        return [{"error": str(exc)}]


def schema_info() -> dict[str, Any]:
    """Return classes, properties, and sample IRIs to help write SPARQL queries."""
    g = _load_graph()

    classes = []
    for cls, lbl in g.query(
        _PREFIXES + "SELECT DISTINCT ?c ?lbl WHERE { ?c a owl:Class ; rdfs:label ?lbl } LIMIT 40"
    ):
        classes.append({"iri": str(cls), "label": str(lbl)})

    obj_props = []
    for prop, lbl in g.query(
        _PREFIXES
        + "SELECT DISTINCT ?p ?lbl WHERE { ?p a owl:ObjectProperty ; rdfs:label ?lbl } LIMIT 30"
    ):
        obj_props.append({"iri": str(prop), "label": str(lbl)})

    dt_props = []
    for prop, lbl in g.query(
        _PREFIXES
        + "SELECT DISTINCT ?p ?lbl WHERE { ?p a owl:DatatypeProperty ; rdfs:label ?lbl } LIMIT 30"
    ):
        dt_props.append({"iri": str(prop), "label": str(lbl)})

    samples = []
    for ind, lbl in g.query(
        _PREFIXES
        + "SELECT DISTINCT ?i ?lbl WHERE { ?i a owl:NamedIndividual ; rdfs:label ?lbl } LIMIT 10"
    ):
        samples.append({"iri": str(ind), "label": str(lbl)})

    return {
        "note": "Use PREFIX : <http://example.org/tfl#> in your queries.",
        "classes": classes,
        "object_properties": obj_props,
        "datatype_properties": dt_props,
        "sample_individuals": samples,
    }


TOOLS = {
    "schema_info": {
        "description": (
            "Returns the ontology schema: all classes, object properties, datatype properties, "
            "and sample individual IRIs. Call this FIRST to understand what to query."
        ),
        "parameters": {},
    },
    "sparql_query": {
        "description": (
            "Execute a SPARQL SELECT query against the knowledge graph. "
            "Returns a list of result rows as dicts. "
            "Prefix : is bound to <http://example.org/tfl#>."
        ),
        "parameters": {"query": "A valid SPARQL SELECT query string."},
    },
}


def call_tool(name: str, params: dict[str, Any]) -> Any:
    if name == "sparql_query":
        return sparql_query(params.get("query", ""))
    if name == "schema_info":
        return schema_info()
    return {"error": f"Unknown tool: {name}"}
