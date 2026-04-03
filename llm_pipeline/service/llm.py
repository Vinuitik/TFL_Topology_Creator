from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

import requests

log = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"
_OLLAMA_URL = "http://ollama:11434/api/generate"
_MODEL = "deepseek-r1:7b"


def _find_latest_prompt(state_name: str) -> Path:
    matches = list(_PROMPTS_DIR.glob(f"{state_name}-v*.txt"))
    if not matches:
        raise FileNotFoundError(f"No prompt found for state '{state_name}' in {_PROMPTS_DIR}")

    def _version(p: Path) -> int:
        m = re.search(r"-v(\d+)\.txt$", p.name)
        return int(m.group(1)) if m else -1

    return max(matches, key=_version)


def _parse_json(raw: str) -> Any:
    # attempt 1: direct parse
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # attempt 2: extract first {...} or [...] block
    m = re.search(r"(\{.*\}|\[.*\])", raw, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass

    raise ValueError(f"Could not parse JSON from LLM response:\n{raw}")


def call_llm(state_name: str, params: str) -> Any:
    prompt_path = _find_latest_prompt(state_name)
    log.info("Using prompt %s", prompt_path.name)

    full_prompt = prompt_path.read_text(encoding="utf-8") + params

    response = requests.post(
        _OLLAMA_URL,
        json={
            "model": _MODEL,
            "prompt": full_prompt,
            "stream": False,
            "options": {"temperature": 0},
        },
    )
    response.raise_for_status()
    raw = response.json()["response"]
    log.debug("LLM raw response: %r", raw)

    return _parse_json(raw)
