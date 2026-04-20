from __future__ import annotations

"""Build an rdflib Graph from validated triples and serialize to Turtle and OWL/XML."""

from typing import Any, Dict, List

from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import OWL, RDF, RDFS, XSD

from schemas import PipelineState

_TFL = Namespace("http://example.org/tfl#")
_PROV = Namespace("http://www.w3.org/ns/prov#")
_GTFS = Namespace("http://vocab.gtfs.org/terms#")
_SCHEMA = Namespace("https://schema.org/")


def build_rdf_graph(triples: List[Dict[str, Any]]) -> Graph:
    """Shared helper: convert a list of triple dicts into a bound rdflib Graph."""
    graph = Graph()
    graph.bind("tfl", _TFL)
    graph.bind("owl", OWL)
    graph.bind("rdf", RDF)
    graph.bind("rdfs", RDFS)
    graph.bind("xsd", XSD)
    graph.bind("prov", _PROV)
    graph.bind("gtfs", _GTFS)
    graph.bind("schema", _SCHEMA)

    for t in triples:
        s = t.get("subject", "")
        p = t.get("predicate", "")
        o = t.get("object", "")
        if not s or not p or not o:
            continue

        s_ref = URIRef(s)
        p_ref = URIRef(p)
        if t.get("is_literal", False):
            datatype = t.get("datatype")
            obj: Any = Literal(o, datatype=URIRef(datatype)) if datatype else Literal(o)
        else:
            obj = URIRef(o)

        graph.add((s_ref, p_ref, obj))

    return graph


def run_turtle_serialization(state: PipelineState) -> PipelineState:
    validated = state.get("validated_ontology", {"triples": []})
    triples = validated.get("triples", [])

    graph = build_rdf_graph(triples)

    turtle_output: str = graph.serialize(format="turtle")
    owl_output: str = graph.serialize(format="xml")

    return {
        "turtle_output": turtle_output,
        "owl_output": owl_output,
    }
