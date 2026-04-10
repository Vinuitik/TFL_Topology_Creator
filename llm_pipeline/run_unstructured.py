from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

from pydantic import BaseModel
from rdflib import Graph, Literal, URIRef

from agent import run_pipeline


def _jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump()
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    if isinstance(value, tuple):
        return [_jsonable(v) for v in value]
    return value


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _save_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=True)


def _merge_unique(rows: Iterable[Dict[str, str]], existing: List[Dict[str, str]], key: str) -> List[Dict[str, str]]:
    index = {r.get(key): r for r in existing if r.get(key)}
    for row in rows:
        row_key = row.get(key)
        if not row_key:
            continue
        index[row_key] = row
    return list(index.values())


def _label_from_iri(iri: str) -> str:
    token = iri.split("#")[-1].split("/")[-1]
    return token.replace("_", " ")


def _update_catalog(catalog: Dict[str, Any], state: Dict[str, Any]) -> Dict[str, Any]:
    mapped = state.get("mapped_graph", {})
    nodes = mapped.get("nodes", [])
    edges = mapped.get("edges", [])

    classes = catalog.get("classes", [])
    predicates = catalog.get("predicates", [])

    class_rows = [
        {
            "label": node.get("class_label") or _label_from_iri(node.get("class_iri", "")),
            "iri": node.get("class_iri", ""),
        }
        for node in nodes
        if node.get("class_iri")
    ]
    predicate_rows = [
        {
            "label": edge.get("predicate_label") or _label_from_iri(edge.get("predicate_iri", "")),
            "iri": edge.get("predicate_iri", ""),
        }
        for edge in edges
        if edge.get("predicate_iri")
    ]

    catalog["classes"] = _merge_unique(class_rows, classes, "iri")
    catalog["predicates"] = _merge_unique(predicate_rows, predicates, "iri")
    return catalog


def _triple_key(triple: Dict[str, Any]) -> Tuple[str, str, str, bool, str]:
    return (
        triple.get("subject", ""),
        triple.get("predicate", ""),
        triple.get("object", ""),
        bool(triple.get("is_literal", False)),
        triple.get("datatype", ""),
    )


def _build_graph(triples: List[Dict[str, Any]]) -> Graph:
    graph = Graph()
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
            if datatype:
                obj = Literal(o, datatype=URIRef(datatype))
            else:
                obj = Literal(o)
        else:
            obj = URIRef(o)

        graph.add((s_ref, p_ref, obj))
    return graph


def main() -> None:
    parser = argparse.ArgumentParser(description="Run KG pipeline sequentially across unstructured files and persist cumulative ontology artifacts.")
    parser.add_argument("--data-dir", default="../data_sources", help="Directory containing Unstructured-*.txt files")
    parser.add_argument("--pattern", default="Unstructured-*.txt", help="Glob pattern for source files")
    parser.add_argument("--output-dir", default="../outputs", help="Directory for run artifacts")
    args = parser.parse_args()

    data_dir = Path(args.data_dir).resolve()
    output_dir = Path(args.output_dir).resolve()
    runs_dir = output_dir / "runs"
    rag_path = output_dir / "rag_catalog.json"

    files = sorted(data_dir.glob(args.pattern))
    if not files:
        raise FileNotFoundError(f"No files found with pattern '{args.pattern}' in {data_dir}")

    rag_catalog = _load_json(rag_path, {"classes": [], "predicates": []})
    all_triples: Dict[Tuple[str, str, str, bool, str], Dict[str, Any]] = {}
    run_summaries: List[Dict[str, Any]] = []

    for idx, file_path in enumerate(files, start=1):
        raw_text = file_path.read_text(encoding="utf-8", errors="ignore")
        metadata = {
            "source": file_path.name,
            "domain": "public-transport",
            "sequence": str(idx),
        }

        result = run_pipeline(raw_text=raw_text, metadata=metadata, rag_catalog=rag_catalog)
        result_json = _jsonable(result)

        run_out_path = runs_dir / f"{idx:02d}_{file_path.stem}.json"
        _save_json(run_out_path, result_json)

        rag_catalog = _update_catalog(rag_catalog, result_json)
        _save_json(rag_path, rag_catalog)

        validated = result_json.get("validated_ontology", {})
        for triple in validated.get("triples", []):
            all_triples[_triple_key(triple)] = triple

        run_summaries.append(
            {
                "file": file_path.name,
                "output": str(run_out_path),
                "triplets": len(result_json.get("triplets", [])),
                "validated_triples": len(validated.get("triples", [])),
                "validation_errors": result_json.get("validation_errors", []),
            }
        )

    final_triples = list(all_triples.values())
    graph = _build_graph(final_triples)

    output_dir.mkdir(parents=True, exist_ok=True)
    owl_path = output_dir / "final.owl"
    ttl_path = output_dir / "final.ttl"
    summary_path = output_dir / "run_summary.json"

    graph.serialize(destination=str(owl_path), format="xml")
    graph.serialize(destination=str(ttl_path), format="turtle")

    summary = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "sources_processed": len(files),
        "runs": run_summaries,
        "final_triples": len(final_triples),
        "owl_path": str(owl_path),
        "ttl_path": str(ttl_path),
        "rag_catalog_path": str(rag_path),
    }
    _save_json(summary_path, summary)

    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
