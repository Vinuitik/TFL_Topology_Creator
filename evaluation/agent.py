"""Single-question agent loop: LLM → parse tool call → execute → feed back → answer."""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

import requests

from tools import TOOLS, call_tool

log = logging.getLogger(__name__)

_MODEL = os.getenv("OLLAMA_ENTITY_MODEL", "qwen2.5:3b")
_URL = os.getenv("OLLAMA_URL", "http://ollama:11434/api/generate")
_TIMEOUT = float(os.getenv("OLLAMA_TIMEOUT_SEC", "120"))
_MAX_TURNS = 6  # schema_info + up to 2 sparql attempts + answer

_SYSTEM = """You are a knowledge graph assistant. You have two tools:

1. schema_info — call this FIRST to discover classes, properties, and example IRIs in the graph.
   Output: {"tool": "schema_info"}

2. sparql_query — execute a SPARQL SELECT against the OWL knowledge graph.
   Output: {"tool": "sparql_query", "query": "<SPARQL SELECT query>"}
   Important: use PREFIX : <http://example.org/tfl#> for all TfL entities.

When you have enough information to answer, output ONLY:
   {"answer": "<your answer>"}

Rules:
- Output ONLY valid JSON on a single line — no explanation, no markdown.
- Always call schema_info first if you are unsure what properties or classes exist.
- If a SPARQL query returns 0 rows, inspect the schema and try a different property."""


def _llm(prompt: str) -> str:
    resp = requests.post(
        _URL,
        json={
            "model": _MODEL,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.1, "repeat_penalty": 1.15, "num_predict": 512},
        },
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json().get("response", "").strip()


def _parse(text: str) -> dict[str, Any] | None:
    for pat in [r"\{.*\}", r"```json\s*(\{.*?\})\s*```"]:
        m = re.search(pat, text, re.DOTALL)
        if m:
            candidate = m.group(1) if "```" in pat else m.group()
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                pass
    return None


def run(question: str) -> dict[str, Any]:
    """Run the agent for one question. Returns {answer, turns}."""
    history = f"{_SYSTEM}\n\nQuestion: {question}\n"
    turns = []

    for turn in range(_MAX_TURNS):
        raw = _llm(history)
        log.debug("Turn %d raw: %s", turn + 1, raw)
        parsed = _parse(raw)

        if parsed is None:
            turns.append({"turn": turn + 1, "raw": raw, "error": "unparseable"})
            break

        if "answer" in parsed:
            turns.append({"turn": turn + 1, "answer": parsed["answer"]})
            return {"answer": parsed["answer"], "turns": turns}

        if "tool" in parsed:
            tool_name = parsed["tool"]
            tool_params = {k: v for k, v in parsed.items() if k != "tool"}
            result = call_tool(tool_name, tool_params)
            turns.append(
                {"turn": turn + 1, "tool": tool_name, "params": tool_params, "result": result}
            )
            # Truncate large schema_info result to avoid filling context
            if tool_name == "schema_info" and isinstance(result, dict):
                result_str = json.dumps(result)[:2000] + "...(truncated)"
            elif isinstance(result, list):
                result_str = json.dumps(result[:10])
            else:
                result_str = json.dumps(result)
            history += f"\nAssistant: {raw}\nTool result: {result_str}\n"
            log.info("Turn %d: %s", turn + 1, tool_name)
        else:
            turns.append({"turn": turn + 1, "raw": raw, "error": "unknown format"})
            break

    return {"answer": None, "turns": turns}
