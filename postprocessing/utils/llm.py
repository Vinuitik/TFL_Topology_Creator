"""LLM client — loads prompts from postprocessing/prompts/, never from llm_pipeline/."""
from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path

import requests

from .config import (
    OLLAMA_MAX_RETRIES,
    OLLAMA_SEED,
    OLLAMA_TEMPERATURE,
    OLLAMA_TIMEOUT_SEC,
    OLLAMA_URL,
    POST_LLM_MODEL,
)

log = logging.getLogger(__name__)
PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


def find_latest_prompt(name: str) -> Path:
    matches = list(PROMPTS_DIR.glob(f"{name}-v*.txt"))
    if not matches:
        raise FileNotFoundError(f"No prompt for '{name}' in {PROMPTS_DIR}")

    def _ver(p: Path) -> int:
        m = re.search(r"-v(\d+)\.txt$", p.name)
        return int(m.group(1)) if m else -1

    return max(matches, key=_ver)


def parse_json(raw: str):
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    m = re.search(r"(\{.*\}|\[.*\])", raw, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    stripped = raw.strip()
    if stripped.startswith("{"):
        ob = stripped.count("{") - stripped.count("}")
        oq = stripped.count("[") - stripped.count("]")
        candidate = stripped.rstrip(", \t\n\r")
        suffix = "]" * max(oq, 0) + "}" * max(ob, 0)
        for closing in [suffix, "]}", "}", ""]:
            try:
                return json.loads(candidate + closing)
            except json.JSONDecodeError:
                continue
    raise ValueError(f"Cannot parse JSON: {raw[:200]}")


def call_llm(prompt_name: str, params: str) -> dict:
    try:
        prompt_path = find_latest_prompt(prompt_name)
    except FileNotFoundError as exc:
        log.warning("Prompt missing: %s", exc)
        return {}

    full_prompt = prompt_path.read_text(encoding="utf-8") + params
    payload = {
        "model": POST_LLM_MODEL,
        "prompt": full_prompt,
        "stream": True,
        "format": "json",
        "options": {
            "temperature": OLLAMA_TEMPERATURE,
            "seed": OLLAMA_SEED,
            "repeat_penalty": 1.15,
        },
    }

    for attempt in range(1, OLLAMA_MAX_RETRIES + 1):
        payload["options"]["seed"] = OLLAMA_SEED + attempt - 1
        accumulated = ""
        try:
            with requests.post(
                OLLAMA_URL, json=payload, stream=True, timeout=OLLAMA_TIMEOUT_SEC
            ) as resp:
                resp.raise_for_status()
                deadline = time.monotonic() + OLLAMA_TIMEOUT_SEC
                for line in resp.iter_lines():
                    if time.monotonic() > deadline:
                        log.warning("LLM stream timeout for %s attempt %d", prompt_name, attempt)
                        break
                    if line:
                        chunk = json.loads(line)
                        accumulated += chunk.get("response", "")
                        if chunk.get("done"):
                            break
        except requests.RequestException as exc:
            log.warning("LLM request error (%s attempt %d): %s", prompt_name, attempt, exc)
            if attempt < OLLAMA_MAX_RETRIES:
                continue
            return {}

        try:
            return parse_json(accumulated)
        except ValueError:
            if attempt < OLLAMA_MAX_RETRIES:
                log.warning("LLM bad JSON for %s attempt %d — retrying", prompt_name, attempt)
                continue
            log.warning("LLM JSON parse failed for %s", prompt_name)
            return {}

    return {}
