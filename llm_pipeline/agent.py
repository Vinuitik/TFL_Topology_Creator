from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

import redis as redis_lib

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
log = logging.getLogger(__name__)

from pydantic import BaseModel
from langgraph.graph import END, StateGraph

from schemas import Document, PipelineState
from states import (
    route_after_validation,
    run_coreference_resolution,
    run_entity_classification,
    run_entity_linking,
    run_extraction,
    run_input_ingestion,
    run_ontology_construction,
    # run_preprocessing,
    run_reasoning,
    run_schema_mapping,
    run_structured_ingestion,
    run_text_normalization,
    run_turtle_serialization,
    run_validation,
)


def build_graph() -> Any:
    """Unstructured pipeline: text → coref → REBEL → entity_linking → … → TTL"""
    graph = StateGraph(PipelineState)

    graph.add_node("input_ingestion", run_input_ingestion)
    # graph.add_node("preprocessing", run_preprocessing)
    graph.add_node("text_normalization", run_text_normalization)
    graph.add_node("coreference_resolution", run_coreference_resolution)
    graph.add_node("extraction", run_extraction)
    graph.add_node("entity_linking", run_entity_linking)
    graph.add_node("entity_classification", run_entity_classification)
    graph.add_node("schema_mapping", run_schema_mapping)
    graph.add_node("ontology_construction", run_ontology_construction)
    graph.add_node("reasoning", run_reasoning)
    graph.add_node("validation", run_validation)
    graph.add_node("turtle_serialization", run_turtle_serialization)

    graph.set_entry_point("input_ingestion")

    # graph.add_edge("input_ingestion", "preprocessing")
    # graph.add_edge("preprocessing", "text_normalization")
    graph.add_edge("input_ingestion", "text_normalization")
    graph.add_edge("text_normalization", "coreference_resolution")
    graph.add_edge("coreference_resolution", "extraction")
    graph.add_edge("extraction", "entity_linking")
    graph.add_edge("entity_linking", "entity_classification")
    graph.add_edge("entity_classification", "schema_mapping")
    graph.add_edge("schema_mapping", "ontology_construction")
    graph.add_edge("ontology_construction", "reasoning")
    graph.add_edge("reasoning", "validation")

    graph.add_conditional_edges(
        "validation",
        route_after_validation,
        {
            "coreference_resolution": "coreference_resolution",
            "extraction": "extraction",
            "entity_linking": "entity_linking",
            "schema_mapping": "schema_mapping",
            "end": "turtle_serialization",
        },
    )
    graph.add_edge("turtle_serialization", END)

    return graph.compile()


def build_structured_graph() -> Any:
    """Structured pipeline: direct parse → entity_linking → … → TTL.

    Skips input_ingestion, text_normalization, coreference_resolution, and
    REBEL extraction entirely.  structured_ingestion produces the same
    ``triplets`` key that run_extraction does, so every downstream node
    (entity_linking through turtle_serialization) runs without modification.
    """
    graph = StateGraph(PipelineState)

    graph.add_node("structured_ingestion", run_structured_ingestion)
    graph.add_node("entity_linking", run_entity_linking)
    graph.add_node("entity_classification", run_entity_classification)
    graph.add_node("schema_mapping", run_schema_mapping)
    graph.add_node("ontology_construction", run_ontology_construction)
    graph.add_node("reasoning", run_reasoning)
    graph.add_node("validation", run_validation)
    graph.add_node("turtle_serialization", run_turtle_serialization)

    graph.set_entry_point("structured_ingestion")

    graph.add_edge("structured_ingestion", "entity_linking")
    graph.add_edge("entity_linking", "entity_classification")
    graph.add_edge("entity_classification", "schema_mapping")
    graph.add_edge("schema_mapping", "ontology_construction")
    graph.add_edge("ontology_construction", "reasoning")
    graph.add_edge("reasoning", "validation")

    # Structured data is high-confidence (parsed, not extracted), so on failure
    # only loop back to schema_mapping — never back to ingestion.
    graph.add_conditional_edges(
        "validation",
        route_after_validation,
        {
            "coreference_resolution": "entity_linking",  # remap — skip coref
            "extraction": "entity_linking",              # remap — skip REBEL
            "entity_linking": "entity_linking",
            "schema_mapping": "schema_mapping",
            "end": "turtle_serialization",
        },
    )
    graph.add_edge("turtle_serialization", END)

    return graph.compile()


def run_pipeline(
    raw_text: str,
    metadata: Dict[str, str] | None = None,
    rag_catalog: Dict[str, Any] | None = None,
) -> PipelineState:
    """Run the unstructured pipeline (REBEL-based extraction)."""
    app = build_graph()
    initial_state: PipelineState = {
        "document": Document(raw_text=raw_text, metadata=metadata or {}),
        "iteration": 0,
    }
    if rag_catalog:
        initial_state["rag_catalog"] = rag_catalog
    result = app.invoke(initial_state)
    return result


def run_structured_pipeline(
    raw_text: str,
    metadata: Dict[str, str] | None = None,
    rag_catalog: Dict[str, Any] | None = None,
) -> PipelineState:
    """Run the structured pipeline (direct parse, no REBEL)."""
    app = build_structured_graph()
    initial_state: PipelineState = {
        "document": Document(raw_text=raw_text, metadata=metadata or {}),
        "iteration": 0,
    }
    if rag_catalog:
        initial_state["rag_catalog"] = rag_catalog
    result = app.invoke(initial_state)
    return result



def _jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump()
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


def _triple_key(t: Dict[str, Any]) -> Tuple[str, str, str, bool, str]:
    return (
        t.get("subject", ""),
        t.get("predicate", ""),
        t.get("object", ""),
        bool(t.get("is_literal", False)),
        t.get("datatype", ""),
    )


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _save_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=True)


def _label_from_iri(iri: str) -> str:
    return iri.split("#")[-1].split("/")[-1].replace("_", " ")


def _update_catalog(catalog: Dict[str, Any], result: Dict[str, Any]) -> Dict[str, Any]:
    mapped = result.get("mapped_graph", {})
    classes: List[Dict[str, str]] = catalog.get("classes", [])
    predicates: List[Dict[str, str]] = catalog.get("predicates", [])

    class_index = {e["iri"]: e for e in classes if e.get("iri")}
    for node in mapped.get("nodes", []):
        iri = node.get("class_iri", "")
        if iri:
            class_index[iri] = {"label": node.get("class_label") or _label_from_iri(iri), "iri": iri}

    pred_index = {e["iri"]: e for e in predicates if e.get("iri")}
    for edge in mapped.get("edges", []):
        iri = edge.get("predicate_iri", "")
        if iri:
            pred_index[iri] = {"label": edge.get("predicate_label") or _label_from_iri(iri), "iri": iri}

    catalog["classes"] = list(class_index.values())
    catalog["predicates"] = list(pred_index.values())
    return catalog


def _flush_annotation_cache() -> None:
    """Delete all *:annotation:* Redis keys so entity_classification always re-runs LLM calls."""
    r = redis_lib.from_url(os.getenv("REDIS_URL", "redis://redis:6379"), decode_responses=True)
    cursor = 0
    deleted = 0
    while True:
        cursor, keys = r.scan(cursor, match="*:annotation:*", count=500)
        if keys:
            r.delete(*keys)
            deleted += len(keys)
        if cursor == 0:
            break
    logging.getLogger(__name__).info("Flushed %d annotation cache keys", deleted)


if __name__ == "__main__":
    from states.turtle_serialization import build_rdf_graph

    parser = argparse.ArgumentParser(description="Run KG pipeline across unstructured files.")
    parser.add_argument("--data-dir", default="../data_sources")
    parser.add_argument("--pattern", default="*.txt,*.json")
    parser.add_argument("--output-dir", default="../outputs")
    args = parser.parse_args()

    data_dir = Path(args.data_dir).resolve()
    output_dir = Path(args.output_dir).resolve()
    runs_dir = output_dir / "runs"
    rag_path = output_dir / "rag_catalog.json"

    patterns = [p.strip() for p in args.pattern.split(",") if p.strip()]
    files: List[Path] = []
    seen: set = set()
    for pat in patterns:
        for f in sorted(data_dir.glob(pat)):
            if f not in seen:
                seen.add(f)
                files.append(f)
    files.sort()
    if not files:
        raise FileNotFoundError(f"No files matching '{args.pattern}' in {data_dir}")

    # Flush annotation cache so entity_classification always runs fresh LLM calls.
    # Canonical/desc/emb keys are intentionally kept — they are reused within this run.
    _flush_annotation_cache()

    hashes_path = output_dir / "file_hashes.json"
    rag_catalog = _load_json(rag_path, {"classes": [], "predicates": []})
    saved_hashes: Dict[str, str] = _load_json(hashes_path, {})
    all_triples: Dict[Tuple, Dict[str, Any]] = {}
    run_summaries: List[Dict[str, Any]] = []
    cumulative_timings: Dict[str, float] = {}

    for idx, file_path in enumerate(files, start=1):
        raw_bytes = file_path.read_bytes()
        file_hash = hashlib.sha256(raw_bytes).hexdigest()
        run_out = runs_dir / f"{idx:02d}_{file_path.stem}.json"

        if saved_hashes.get(file_path.name) == file_hash and run_out.exists():
            log.info("CACHE HIT %s — skipping pipeline", file_path.name)
            result_json = _load_json(run_out, {})
            cache_hit = True
        else:
            raw_text = raw_bytes.decode("utf-8", errors="ignore")

            # Auto-detect structured vs unstructured by filename prefix.
            is_structured = file_path.stem.lower().startswith("structured")
            if is_structured:
                log.info("STRUCTURED path selected for %s", file_path.name)
                result = run_structured_pipeline(
                    raw_text=raw_text,
                    metadata={"source": file_path.name, "domain": "public-transport", "sequence": str(idx)},
                    rag_catalog=rag_catalog,
                )
            else:
                result = run_pipeline(
                    raw_text=raw_text,
                    metadata={"source": file_path.name, "domain": "public-transport", "sequence": str(idx)},
                    rag_catalog=rag_catalog,
                )
            result_json = _jsonable(result)
            _save_json(run_out, result_json)
            saved_hashes[file_path.name] = file_hash
            _save_json(hashes_path, saved_hashes)
            cache_hit = False

        rag_catalog = _update_catalog(rag_catalog, result_json)
        _save_json(rag_path, rag_catalog)

        validated = result_json.get("validated_ontology", {})
        for t in validated.get("triples", []):
            all_triples[_triple_key(t)] = t

        timings = result_json.get("timings", {})
        for stage, elapsed in timings.items():
            cumulative_timings[stage] = cumulative_timings.get(stage, 0.0) + elapsed

        run_summaries.append({
            "file": file_path.name,
            "cache_hit": cache_hit,
            "output": str(run_out),
            "triplets": len(result_json.get("triplets", [])),
            "validated_triples": len(validated.get("triples", [])),
            "validation_errors": result_json.get("validation_errors", []),
            "per_stage_timings": timings,
        })

    output_dir.mkdir(parents=True, exist_ok=True)
    final_triples = list(all_triples.values())
    graph = build_rdf_graph(final_triples)

    owl_path = output_dir / "final.owl"
    ttl_path = output_dir / "final.ttl"
    graph.serialize(destination=str(owl_path), format="xml")
    graph.serialize(destination=str(ttl_path), format="turtle")

    summary = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "sources_processed": len(files),
        "runs": run_summaries,
        "final_triples": len(final_triples),
        "cumulative_timings": cumulative_timings,
        "owl_path": str(owl_path),
        "ttl_path": str(ttl_path),
        "rag_catalog_path": str(rag_path),
    }
    _save_json(output_dir / "run_summary.json", summary)
    
    print("\n" + "="*50)
    print(" PIPELINE PROFILING REPORT ".center(50, "="))
    print("="*50)
    print(f"{'Stage':<30} | {'Total Time (s)':>15}")
    print("-" * 50)
    
    # Sort timings from slowest to fastest
    sorted_timings = sorted(cumulative_timings.items(), key=lambda x: x[1], reverse=True)
    total_pipeline_time = sum(cumulative_timings.values())
    
    for stage, t in sorted_timings:
        print(f"{stage:<30} | {t:>14.2f}s")
    
    print("-" * 50)
    print(f"{'TOTAL PIPELINE CPU/GPU TIME':<30} | {total_pipeline_time:>14.2f}s")
    print("="*50 + "\n")
    print(f"✅ Pipeline complete! Final graph saved to {ttl_path}")
