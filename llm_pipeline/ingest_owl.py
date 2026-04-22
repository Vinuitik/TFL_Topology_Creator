from __future__ import annotations

"""Seed Redis entity cache and rag_catalog.json from OWL/TTL files in inputs/.

Run before agent.py on every pipeline execution. Reads all *.owl, *.ttl, *.rdf
files from --inputs-dir, extracts classes, properties, and named individuals,
generates descriptions via Ollama LLM, embeds them, and writes to Redis and
rag_catalog.json so entity_linking and schema_mapping can reuse the knowledge.

Hash-gated: files whose SHA-256 matches outputs/ingest_hashes.json AND whose
Redis entries still exist are skipped — no re-embedding on unchanged inputs.
"""

import argparse
import hashlib
import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple

import time

import redis as redis_lib
import requests
import rdflib
from rdflib.namespace import OWL, RDF, RDFS

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)

_REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379")
_EMBED_URL = os.getenv("OLLAMA_EMBED_URL")
_EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL")
_LLM_URL = os.getenv("OLLAMA_URL")
_LLM_MODEL = os.getenv("OLLAMA_ENTITY_MODEL")
_LLM_TIMEOUT = float(os.getenv("OLLAMA_TIMEOUT_SEC"))

_PROMPTS_DIR = Path(__file__).parent / "prompts"


def _get_redis() -> redis_lib.Redis:
    return redis_lib.from_url(_REDIS_URL, decode_responses=True)


def _local_name(uri: rdflib.URIRef) -> str:
    s = str(uri)
    frag = s.split("#")[-1].split("/")[-1]
    return re.sub(r"[_-]+", " ", frag).strip() or s


def _label(g: rdflib.Graph, uri: rdflib.URIRef) -> str:
    val = g.value(uri, RDFS.label)
    return str(val).strip() if val else _local_name(uri)


def _context_str(g: rdflib.Graph, uri: rdflib.URIRef, label: str) -> str:
    parts: List[str] = [label]
    comment = g.value(uri, RDFS.comment)
    if comment:
        parts.append(str(comment).strip())
    parent = g.value(uri, RDFS.subClassOf)
    if parent and isinstance(parent, rdflib.URIRef):
        parts.append(f"subclass of {_label(g, parent)}")
    domain = g.value(uri, RDFS.domain)
    if domain and isinstance(domain, rdflib.URIRef):
        parts.append(f"domain {_label(g, domain)}")
    range_ = g.value(uri, RDFS.range)
    if range_ and isinstance(range_, rdflib.URIRef):
        parts.append(f"range {_label(g, range_)}")
    return "; ".join(parts)


def _llm_describe(label: str) -> str:
    prompt_path = max(
        _PROMPTS_DIR.glob("entity_linking_describe-v*.txt"),
        key=lambda p: int(re.search(r"-v(\d+)\.txt$", p.name).group(1)),
    )
    full_prompt = prompt_path.read_text(encoding="utf-8") + f"\nName: {label}\n"
    log.info("LLM describe → model=%s url=%s prompt_chars=%d label='%s'",
             _LLM_MODEL, _LLM_URL, len(full_prompt), label)
    t0 = time.monotonic()
    try:
        r = requests.post(
            _LLM_URL,
            json={"model": _LLM_MODEL, "prompt": full_prompt, "stream": False, "options": {"temperature": 0}},
            timeout=_LLM_TIMEOUT,
        )
        elapsed = time.monotonic() - t0
        log.info("LLM describe ← status=%d elapsed=%.1fs label='%s'", r.status_code, elapsed, label)
        r.raise_for_status()
        raw = r.json().get("response", "")
        m = re.search(r'\{.*\}', raw, re.DOTALL)
        if m:
            return json.loads(m.group()).get("description", label)
    except Exception as exc:
        elapsed = time.monotonic() - t0
        log.warning("LLM describe failed for '%s' after %.1fs: %s: %s",
                    label, elapsed, type(exc).__name__, exc)
    return label


def _embed(text: str) -> List[float]:
    log.info("Embed → model=%s url=%s text_chars=%d", _EMBED_MODEL, _EMBED_URL, len(text))
    t0 = time.monotonic()
    try:
        r = requests.post(_EMBED_URL, json={"model": _EMBED_MODEL, "prompt": text}, timeout=60)
        elapsed = time.monotonic() - t0
        log.info("Embed ← status=%d elapsed=%.1fs", r.status_code, elapsed)
        r.raise_for_status()
        return r.json().get("embedding", [])
    except Exception as exc:
        elapsed = time.monotonic() - t0
        log.warning("Embedding failed after %.1fs: %s: %s", elapsed, type(exc).__name__, exc)
        return []


def _extract(g: rdflib.Graph) -> Tuple[List[Dict], List[Dict]]:
    """Return (entities, relations) as lists of {label, iri, context_str}."""
    entities: Dict[str, Dict] = {}
    relations: Dict[str, Dict] = {}

    # OWL classes
    for uri in g.subjects(RDF.type, OWL.Class):
        if not isinstance(uri, rdflib.URIRef):
            continue
        lbl = _label(g, uri)
        entities[lbl] = {"label": lbl, "iri": str(uri), "context": _context_str(g, uri, lbl)}

    # Named individuals + instances of extracted classes
    for uri in g.subjects(RDF.type, OWL.NamedIndividual):
        if not isinstance(uri, rdflib.URIRef):
            continue
        lbl = _label(g, uri)
        entities[lbl] = {"label": lbl, "iri": str(uri), "context": _context_str(g, uri, lbl)}

    # Also catch rdf:type triples pointing to known classes
    known_class_iris = {e["iri"] for e in entities.values()}
    for uri, _, cls in g.triples((None, RDF.type, None)):
        if not isinstance(uri, rdflib.URIRef) or not isinstance(cls, rdflib.URIRef):
            continue
        if str(cls) in known_class_iris and str(uri) not in {e["iri"] for e in entities.values()}:
            lbl = _label(g, uri)
            entities[lbl] = {"label": lbl, "iri": str(uri), "context": _context_str(g, uri, lbl)}

    # Object properties
    for uri in g.subjects(RDF.type, OWL.ObjectProperty):
        if not isinstance(uri, rdflib.URIRef):
            continue
        lbl = _label(g, uri)
        relations[lbl] = {"label": lbl, "iri": str(uri), "context": _context_str(g, uri, lbl), "property_type": "object_property"}

    # Datatype properties
    for uri in g.subjects(RDF.type, OWL.DatatypeProperty):
        if not isinstance(uri, rdflib.URIRef):
            continue
        lbl = _label(g, uri)
        relations[lbl] = {"label": lbl, "iri": str(uri), "context": _context_str(g, uri, lbl), "property_type": "datatype_property"}

    return list(entities.values()), list(relations.values())


def _write_to_redis(r: redis_lib.Redis, category: str, items: List[Dict]) -> int:
    # Phase 1 — all descriptions first (one model load for qwen2.5)
    descriptions: Dict[str, str] = {}
    for item in items:
        lbl = item["label"]
        ctx = item["context"]
        log.info("[%s] describing '%s' (ctx_words=%d)", category, lbl, len(ctx.split()))
        desc = ctx if len(ctx.split()) >= 8 else _llm_describe(lbl)
        r.set(f"{category}:desc:{lbl}", desc)
        descriptions[lbl] = desc

    # Phase 2 — all embeddings after (one model swap to mxbai-embed-large)
    written = 0
    for item in items:
        lbl = item["label"]
        vec = _embed(descriptions[lbl])
        r.set(f"{category}:emb:{lbl}", json.dumps(vec))
        written += 1

    return written


def _merge_catalog(catalog: Dict, entities: List[Dict], relations: List[Dict]) -> Tuple[int, int]:
    existing_class_iris = {e["iri"] for e in catalog.get("classes", [])}
    existing_pred_iris = {e["iri"] for e in catalog.get("predicates", [])}

    new_classes = 0
    # Create a lookup for existing classes to avoid duplicates, but we will refresh them
    class_index = {c["iri"]: i for i, c in enumerate(catalog.setdefault("classes", []))}
    for e in entities:
        entry = {"label": e["label"], "iri": e["iri"]}
        if e["iri"] in class_index:
            catalog["classes"][class_index[e["iri"]]] = entry
        else:
            catalog["classes"].append(entry)
            new_classes += 1

    new_preds = 0
    pred_index = {p["iri"]: i for i, p in enumerate(catalog.setdefault("predicates", []))}
    for r in relations:
        entry = {
            "label": r["label"],
            "iri": r["iri"],
            "property_type": r.get("property_type", "object_property")
        }
        if r["iri"] in pred_index:
            catalog["predicates"][pred_index[r["iri"]]] = entry
        else:
            catalog["predicates"].append(entry)
            new_preds += 1

    return new_classes, new_preds


def _redis_has_entries(r: redis_lib.Redis, category: str, labels: List[str]) -> bool:
    """Spot-check: return True if at least one desc key exists for the given labels."""
    for lbl in labels[:5]:  # sample first 5
        if r.exists(f"{category}:desc:{lbl}"):
            return True
    return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed Redis and rag_catalog from OWL/TTL files.")
    parser.add_argument("--inputs-dir", default="../inputs")
    parser.add_argument("--output-dir", default="../outputs")
    args = parser.parse_args()

    inputs_dir = Path(args.inputs_dir).resolve()
    output_dir = Path(args.output_dir).resolve()
    catalog_path = output_dir / "rag_catalog.json"
    hashes_path = output_dir / "ingest_hashes.json"

    files = (
        list(inputs_dir.glob("*.owl"))
        + list(inputs_dir.glob("*.ttl"))
        + list(inputs_dir.glob("*.rdf"))
    )

    if not files:
        log.info("No OWL/TTL/RDF files found in %s — skipping ingestion.", inputs_dir)
        print(json.dumps({"files_ingested": 0, "skipped": "no input files"}))
        sys.exit(0)

    # Preflight: check Ollama is up and which models are loaded
    try:
        tags = requests.get(_LLM_URL.replace("/api/generate", "/api/tags"), timeout=5).json()
        loaded = [m["name"] for m in tags.get("models", [])]
        log.info("Ollama preflight OK — models available: %s", loaded)
    except Exception as exc:
        log.warning("Ollama preflight failed: %s: %s", type(exc).__name__, exc)

    r = _get_redis()

    catalog: Dict = {"classes": [], "predicates": []}
    if catalog_path.exists():
        with catalog_path.open(encoding="utf-8") as f:
            catalog = json.load(f)

    saved_hashes: Dict[str, str] = {}
    if hashes_path.exists():
        with hashes_path.open(encoding="utf-8") as f:
            saved_hashes = json.load(f)

    total_entities = 0
    total_relations = 0
    total_new_classes = 0
    total_new_preds = 0
    files_skipped = 0

    for path in files:
        file_hash = hashlib.sha256(path.read_bytes()).hexdigest()

        if saved_hashes.get(path.name) == file_hash:
            # Hash matches — check Redis still has the data (guard against flush)
            g = rdflib.Graph()
            g.parse(str(path))
            entities, relations = _extract(g)
            entity_labels = [e["label"] for e in entities]
            if _redis_has_entries(r, "entities", entity_labels):
                log.info("CACHE HIT %s — skipping re-embed (%d entities)", path.name, len(entities))
                new_cls, new_preds = _merge_catalog(catalog, entities, relations)
                total_new_classes += new_cls
                total_new_preds += new_preds
                files_skipped += 1
                continue
            log.info("Hash match but Redis empty for %s — re-ingesting", path.name)
        else:
            log.info("Parsing %s ...", path.name)
            g = rdflib.Graph()
            g.parse(str(path))
            entities, relations = _extract(g)
            log.info("  %d entities, %d relations extracted", len(entities), len(relations))

        ent_written = _write_to_redis(r, "entities", entities)
        rel_written = _write_to_redis(r, "relations", relations)
        total_entities += ent_written
        total_relations += rel_written

        new_cls, new_preds = _merge_catalog(catalog, entities, relations)
        total_new_classes += new_cls
        total_new_preds += new_preds

        saved_hashes[path.name] = file_hash

    output_dir.mkdir(parents=True, exist_ok=True)
    with catalog_path.open("w", encoding="utf-8") as f:
        json.dump(catalog, f, indent=2, ensure_ascii=True)
    with hashes_path.open("w", encoding="utf-8") as f:
        json.dump(saved_hashes, f, indent=2, ensure_ascii=True)

    summary = {
        "files_ingested": len(files) - files_skipped,
        "files_skipped_cache": files_skipped,
        "entities_written": total_entities,
        "relations_written": total_relations,
        "rag_catalog_new_classes": total_new_classes,
        "rag_catalog_new_predicates": total_new_preds,
    }
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
