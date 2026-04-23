"""Embedding helpers: fetch from Redis cache or generate via Ollama."""
from __future__ import annotations

import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Tuple

import redis
import requests
from rdflib import URIRef

from utils.config import EMBED_WORKERS, OLLAMA_EMBED_MODEL, OLLAMA_EMBED_URL, OLLAMA_TIMEOUT_SEC, REDIS_URL

log = logging.getLogger(__name__)

_redis_client: redis.Redis | None = None


def get_redis() -> redis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.from_url(REDIS_URL, decode_responses=True)
    return _redis_client


def embed(text: str) -> List[float]:
    for attempt in range(3):
        try:
            r = requests.post(
                OLLAMA_EMBED_URL,
                json={"model": OLLAMA_EMBED_MODEL, "prompt": text},
                timeout=OLLAMA_TIMEOUT_SEC,
            )
            r.raise_for_status()
            return r.json().get("embedding", [])
        except Exception as exc:
            if attempt < 2:
                time.sleep(0.5 * (attempt + 1))
            else:
                log.warning("Embed failed for '%s': %s", text[:40], exc)
    return []


def get_embeddings(
    iris: List[URIRef], labels: Dict[URIRef, str], category: str
) -> Dict[URIRef, List[float]]:
    r = get_redis()
    embeds: Dict[URIRef, List[float]] = {}
    needs_embed: List[URIRef] = []

    for iri in iris:
        label = labels[iri]
        found = False
        for key in (
            f"{category}:emb:{label}",
            f"entities:emb:{label}",
            f"relations:emb:{label}",
            f"entities_class:emb:{label}",
            f"entities_individual:emb:{label}",
        ):
            raw = r.get(key)
            if raw:
                try:
                    embeds[iri] = json.loads(raw)
                    found = True
                    break
                except json.JSONDecodeError:
                    pass
        if not found:
            needs_embed.append(iri)

    if needs_embed:
        log.info(
            "Generating %d embedding(s) not in Redis (category=%s)...",
            len(needs_embed), category,
        )

        def _do(iri: URIRef) -> Tuple[URIRef, List[float]]:
            return iri, embed(labels[iri])

        with ThreadPoolExecutor(max_workers=EMBED_WORKERS) as pool:
            for iri, emb in pool.map(_do, needs_embed):
                if emb:
                    embeds[iri] = emb

    return embeds
