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
_MAX_TURNS = 4

_SYSTEM = """You are a knowledge graph assistant. You have access to one tool:

sparql_query — execute a SPARQL SELECT query against an OWL knowledge graph.
Common prefixes pre-bound: owl, rdf, rdfs, xsd, ex (http://example.org/).

To call the tool output ONLY this JSON (no explanation):
{"tool": "sparql_query", "query": "<SPARQL SELECT query>"}

When you have enough information to answer, output ONLY this JSON:
{"answer": "<your answer>"}

Never output anything else — only valid JSON on a single line."""


def _llm(prompt: str) -> str:
    resp = requests.post(
        _URL,
        json={"model": _MODEL, "prompt": prompt, "stream": False,
              "options": {"temperature": 0.1, "repeat_penalty": 1.15, "num_predict": 512}},
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json().get("response", "").strip()


def _parse(text: str) -> dict[str, Any] | None:
    for pat in [r'\{.*\}', r'```json\s*(\{.*?\})\s*```']:
        m = re.search(pat, text, re.DOTALL)
        if m:
            candidate = m.group(1) if '```' in pat else m.group()
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                pass
    return None


def run(question: str) -> dict[str, Any]:
    """Run the agent for a single question. Returns {"answer": str, "turns": list}."""
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
            turns.append({"turn": turn + 1, "tool": tool_name, "params": tool_params, "result": result})
            result_str = json.dumps(result[:10] if isinstance(result, list) else result)
            history += f"\nAssistant: {raw}\nTool result: {result_str}\n"
            log.info("Turn %d: %s → %d rows", turn + 1, tool_name,
                     len(result) if isinstance(result, list) else 1)
        else:
            turns.append({"turn": turn + 1, "raw": raw, "error": "unknown format"})
            break

    return {"answer": None, "turns": turns}
