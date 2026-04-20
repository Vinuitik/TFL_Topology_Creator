"""
states/structured_ingestion.py

Converts structured data files (JSON, tab-separated TfL API dumps) directly
into Triplet objects, bypassing text_normalization → coreference → REBEL.

The output is the same `triplets` list that the extraction stage produces,
so the downstream pipeline (entity_linking → ... → turtle_serialization)
runs identically for both structured and unstructured data.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List

from schemas import PipelineState
from schemas.entities import Triplet

log = logging.getLogger(__name__)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _camel_to_label(key: str) -> str:
    """'isFarePaying' → 'is fare paying'  |  'modeName' → 'mode name'"""
    spaced = re.sub(r"([A-Z])", r" \1", key).strip()
    return spaced.lower()


def _triplet(subject: str, predicate: str, obj: str) -> Triplet:
    return Triplet(
        subject=subject,
        predicate=predicate,
        object=obj,
        confidence=1.0,
        provenance_sentence=f"{subject} {predicate} {obj}",
    )


# ── JSON parser ───────────────────────────────────────────────────────────────

def _json_to_triplets(data: Any) -> List[Triplet]:
    """
    Recursively convert a parsed JSON structure to Triplets.
    Handles both list-of-objects and single-object patterns from the TfL API.
    """
    items: list = data if isinstance(data, list) else [data]
    triplets: List[Triplet] = []

    for item in items:
        if not isinstance(item, dict):
            continue

        # Determine the subject label: prefer name/modeName/id fields
        subject = (
            item.get("name")
            or item.get("modeName")
            or item.get("id")
            or item.get("naptanId")
            or item.get("stationName")
            or "unknown"
        )
        subject = str(subject).strip()

        for key, value in item.items():
            if key in ("$type", "name", "modeName", "id", "naptanId", "stationName"):
                continue

            predicate = _camel_to_label(key)

            if isinstance(value, (str, bool, int, float)):
                triplets.append(_triplet(subject, predicate, str(value)))

            elif isinstance(value, list):
                for element in value:
                    if isinstance(element, str):
                        triplets.append(_triplet(subject, predicate, element))
                    elif isinstance(element, dict):
                        # Recurse — treat nested objects as linked entities
                        nested_name = (
                            element.get("name")
                            or element.get("modeName")
                            or element.get("id")
                            or element.get("naptanId")
                        )
                        if nested_name:
                            triplets.append(_triplet(subject, predicate, str(nested_name)))
                        triplets.extend(_json_to_triplets(element))

            elif isinstance(value, dict):
                nested_name = (
                    value.get("name")
                    or value.get("modeName")
                    or value.get("id")
                )
                if nested_name:
                    triplets.append(_triplet(subject, predicate, str(nested_name)))
                triplets.extend(_json_to_triplets(value))

    return triplets


# ── TSV / key-value parser ────────────────────────────────────────────────────

def _tsv_to_triplets(text: str) -> List[Triplet]:
    """
    Parse tab-separated TfL API key-value dumps.
    Buffers blocks separated by integer lines to ensure the subject (e.g. modeName)
    applies to all properties in the block, regardless of line order.
    """
    triplets: List[Triplet] = []
    _NAME_KEYS = {"mode name", "name", "id", "naptan id", "station name"}

    block_lines = []

    def process_block():
        if not block_lines:
            return
            
        subject = None
        for k, v in block_lines:
            if k.lower() in _NAME_KEYS:
                subject = v
                break
                
        if not subject:
            subject = "unknown"
            
        for k, v in block_lines:
            if k.lower() in ("$type",) or k.lower() in _NAME_KEYS:
                continue
            triplets.append(_triplet(subject, k, v))

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        parts = line.split("\t")
        
        # Separator: no tab, or key is an array header
        if len(parts) == 1 or parts[0].strip().startswith("["):
            process_block()
            block_lines = []
            continue

        k_raw, v = parts[0].strip(), parts[1].strip().strip('"')
        
        if k_raw.isdigit():
            process_block()
            block_lines = []
            
        if not v or k_raw in ("$type",):
            continue

        if v.startswith("{") and "id:" in v:
            # Fallback for unexpanded inline objects
            m_name = re.search(r'name:\s*"([^"]+)"', v)
            m_id = re.search(r'id:\s*"([^"]+)"', v)
            inline_sub = (m_name.group(1) if m_name else None) or (m_id.group(1) if m_id else None)
            if inline_sub:
                block_lines.append(("name", inline_sub))
            continue

        k_label = _camel_to_label(k_raw)
        block_lines.append((k_label, v))

    process_block()
    return triplets


# ── Entrypoint ────────────────────────────────────────────────────────────────

def run_structured_ingestion(state: PipelineState) -> PipelineState:
    """
    LangGraph node.  Reads raw_text from state and converts structured content
    to Triplets.  Produces the same `triplets` key that run_extraction does,
    so the rest of the graph (entity_linking onward) is unchanged.
    """
    doc = state.get("document")
    if doc is None:
        log.warning("structured_ingestion: no document in state")
        return {}

    raw_text: str = getattr(doc, "raw_text", "") or ""
    raw_text = raw_text.strip()

    triplets: List[Triplet] = []

    # Try JSON first
    if raw_text.startswith(("{", "[")):
        try:
            data = json.loads(raw_text)
            triplets = _json_to_triplets(data)
            log.info("structured_ingestion: JSON → %d triplets", len(triplets))
        except json.JSONDecodeError as exc:
            log.warning("structured_ingestion: JSON parse failed (%s), falling back to TSV", exc)
            triplets = _tsv_to_triplets(raw_text)
    else:
        triplets = _tsv_to_triplets(raw_text)
        log.info("structured_ingestion: TSV → %d triplets", len(triplets))

    if not triplets:
        log.warning("structured_ingestion: produced 0 triplets — check input format")

    return {
        "triplets": triplets,
        "low_confidence": len(triplets) == 0,
    }
