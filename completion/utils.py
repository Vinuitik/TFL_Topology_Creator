"""Utility functions for completion pipeline."""
from __future__ import annotations

import json
import logging
import re
from math import sqrt
from typing import Any

import requests
from rdflib import Literal, URIRef

from config import (
    OLLAMA_EMBED_MODEL,
    OLLAMA_EMBED_URL,
    OLLAMA_ENTITY_MODEL,
    OLLAMA_TIMEOUT_SEC,
    OLLAMA_URL,
)

log = logging.getLogger(__name__)

PREFIXES = """
PREFIX owl:  <http://www.w3.org/2002/07/owl#>
PREFIX rdf:  <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX xsd:  <http://www.w3.org/2001/XMLSchema#>
PREFIX :     <http://example.org/tfl#>
"""


def normalize_ws(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


def embed(text: str) -> list[float]:
    if not text:
        return []
    resp = requests.post(
        OLLAMA_EMBED_URL,
        json={"model": OLLAMA_EMBED_MODEL, "prompt": text},
        timeout=OLLAMA_TIMEOUT_SEC,
    )
    resp.raise_for_status()
    return resp.json().get("embedding", [])


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return -1.0
    dot = sum(x * y for x, y in zip(a, b))
    na = sqrt(sum(x * x for x in a))
    nb = sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return -1.0
    return dot / (na * nb)


def call_llm_json(instruction: str) -> dict[str, Any]:
    payload = {
        "model": OLLAMA_ENTITY_MODEL,
        "prompt": instruction,
        "stream": False,
        "format": "json",
        "options": {"temperature": 0.1, "repeat_penalty": 1.15, "num_predict": 700},
    }
    resp = requests.post(OLLAMA_URL, json=payload, timeout=OLLAMA_TIMEOUT_SEC)
    resp.raise_for_status()
    raw = resp.json().get("response", "").strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"(\{.*\}|\[.*\])", raw, re.DOTALL)
        if not m:
            return {"error": f"Invalid JSON response: {raw[:200]}"}
        try:
            value = json.loads(m.group(1))
            if isinstance(value, dict):
                return value
            return {"data": value}
        except json.JSONDecodeError:
            return {"error": f"Invalid JSON response: {raw[:200]}"}


def sparql_rows(graph, query: str) -> list[dict[str, str]]:
    res = graph.query(PREFIXES + "\n" + query)
    return [{str(v): str(val) for v, val in zip(res.vars, row)} for row in res]


def to_node(value: str):
    if value.startswith("http://") or value.startswith("https://"):
        return URIRef(value)
    return Literal(value)


def to_jsonable_node(node) -> str:
    if isinstance(node, URIRef):
        return str(node)
    if isinstance(node, Literal):
        return str(node)
    return str(node)
