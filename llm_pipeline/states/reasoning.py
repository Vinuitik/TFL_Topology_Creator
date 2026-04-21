from __future__ import annotations

"""Add inferred facts on top of the draft ontology."""

from typing import Dict, List, Set, Tuple

from schemas import PipelineState


_RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
_PT_CONNECTED = "http://example.org/pt#ConnectedEntity"
_PT_OPERATES = "http://example.org/pt#operates"
_PT_OPERATED_BY = "http://example.org/pt#operatedBy"
_PT_RELATED_TO = "http://example.org/pt#relatedTo"


def _key(triple: Dict[str, str]) -> Tuple[str, str, str, bool, str]:
    return (
        triple.get("subject", ""),
        triple.get("predicate", ""),
        triple.get("object", ""),
        bool(triple.get("is_literal", False)),
        triple.get("datatype", ""),
    )


def run_reasoning(state: PipelineState) -> PipelineState:
    draft = state.get("ontology_draft", {"triples": []})
    triples = list(draft.get("triples", []))

    inferred: List[Dict[str, str]] = list(triples)
    seen: Set[Tuple[str, str, str, bool, str]] = {_key(t) for t in triples}

    for t in triples:
        if t.get("is_literal", False):
            continue

        s = t.get("subject", "")
        p = t.get("predicate", "")
        o = t.get("object", "")
        if not s or not p or not o:
            continue

        # All nodes in at least one relation are typed as ConnectedEntity.
        if p != _RDF_TYPE:
            node_type = {
                "subject": s,
                "predicate": _RDF_TYPE,
                "object": _PT_CONNECTED,
                "is_literal": False,
            }
            k = _key(node_type)
            if k not in seen:
                seen.add(k)
                inferred.append(node_type)

        # Inverse rule for operates / operatedBy.
        if p == _PT_OPERATES:
            inv = {"subject": o, "predicate": _PT_OPERATED_BY, "object": s, "is_literal": False}
            k = _key(inv)
            if k not in seen:
                seen.add(k)
                inferred.append(inv)
        elif p == _PT_OPERATED_BY:
            inv = {"subject": o, "predicate": _PT_OPERATES, "object": s, "is_literal": False}
            k = _key(inv)
            if k not in seen:
                seen.add(k)
                inferred.append(inv)

        # relatedTo is symmetric.
        if p == _PT_RELATED_TO:
            sym = {"subject": o, "predicate": _PT_RELATED_TO, "object": s, "is_literal": False}
            k = _key(sym)
            if k not in seen:
                seen.add(k)
                inferred.append(sym)

    return {
        "inferred_ontology": {"triples": inferred},
        "inferred_triples_count": max(0, len(inferred) - len(triples)),
    }
