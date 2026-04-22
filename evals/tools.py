"""SPARQL tool executed against the pipeline's output graph (outputs/final.ttl)."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from rdflib import ConjunctiveGraph

log = logging.getLogger(__name__)

_graph: ConjunctiveGraph | None = None
_TTL_PATH = Path(__file__).parent.parent / "outputs" / "final.ttl"
_OWL_PATH = Path(__file__).parent.parent / "outputs" / "final.owl"


def _load_graph() -> ConjunctiveGraph:
    global _graph
    if _graph is not None:
        return _graph
    g = ConjunctiveGraph()
    for path, fmt in [(_TTL_PATH, "turtle"), (_OWL_PATH, "xml")]:
        if path.exists():
            g.parse(str(path), format=fmt)
            log.info("Loaded graph from %s (%d triples)", path, len(g))
            _graph = g
            return g
    raise FileNotFoundError(f"No graph found at {_TTL_PATH} or {_OWL_PATH}. Run the pipeline first.")


# ── tool registry ────────────────────────────────────────────────────────────

TOOLS = {
    "sparql_query": {
        "description": (
            "Execute a SPARQL SELECT query against the knowledge graph. "
            "Returns a list of result rows as dicts. "
            "Common prefixes are pre-bound: owl, rdf, rdfs, xsd, ex."
        ),
        "parameters": {
            "query": "A valid SPARQL SELECT query string."
        },
    }
}

_PREFIXES = """
PREFIX owl:  <http://www.w3.org/2002/07/owl#>
PREFIX rdf:  <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX xsd:  <http://www.w3.org/2001/XMLSchema#>
PREFIX ex:   <http://example.org/>
"""


def sparql_query(query: str) -> list[dict[str, Any]]:
    g = _load_graph()
    full_query = _PREFIXES + "\n" + query
    try:
        results = g.query(full_query)
        rows = []
        for row in results:
            rows.append({str(var): str(val) for var, val in zip(results.vars, row)})
        log.info("SPARQL returned %d rows", len(rows))
        return rows
    except Exception as exc:
        log.warning("SPARQL error: %s", exc)
        return [{"error": str(exc)}]


def call_tool(name: str, params: dict[str, Any]) -> Any:
    if name == "sparql_query":
        return sparql_query(params.get("query", ""))
    return {"error": f"Unknown tool: {name}"}
