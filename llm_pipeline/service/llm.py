from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any

import requests

log = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"
_OLLAMA_URL = os.getenv("OLLAMA_URL")
_MODEL = os.getenv("OLLAMA_ENTITY_MODEL")
_TIMEOUT_SEC = float(os.getenv("OLLAMA_TIMEOUT_SEC"))
_MAX_RETRIES = int(os.getenv("OLLAMA_MAX_RETRIES"))
_BACKOFF_SEC = float(os.getenv("OLLAMA_BACKOFF_SEC"))


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

    # attempt 3: fix truncated JSON by progressively closing open brackets
    stripped = raw.strip()
    if stripped.startswith("{"):
        # count unclosed brackets and close them
        open_braces = stripped.count("{") - stripped.count("}")
        open_brackets = stripped.count("[") - stripped.count("]")
        # strip any trailing incomplete token (e.g. mid-string or mid-key)
        candidate = stripped.rstrip(", \t\n\r")
        # remove trailing incomplete object fragment like `{"subject": "foo`
        candidate = re.sub(r',\s*\{[^}]*$', '', candidate)
        suffix = "]" * max(open_brackets, 0) + "}" * max(open_braces, 0)
        for closing in [suffix, "]}", "}", ""]:
            try:
                return json.loads(candidate + closing)
            except json.JSONDecodeError:
                continue

    raise ValueError(f"Could not parse JSON from LLM response:\n{raw}")


def call_llm(
    state_name: str,
    params: str,
    model: str | None = None,
    extra_options: dict | None = None,
) -> Any:
    prompt_path = _find_latest_prompt(state_name)
    log.info("Using prompt %s", prompt_path.name)

    full_prompt = prompt_path.read_text(encoding="utf-8") + params
    effective_model = model or _MODEL

    options = {"temperature": 0, "repeat_penalty": 1.15}
    if extra_options:
        options.update(extra_options)

    payload = {
        "model": effective_model,
        "prompt": full_prompt,
        "stream": False,
        "format": "json",
        "options": options,
    }

    log.info("LLM → state=%s model=%s url=%s prompt_chars=%d",
             state_name, effective_model, _OLLAMA_URL, len(full_prompt))
    last_exc: Exception | None = None
    for attempt in range(1, _MAX_RETRIES + 1):
        t0 = time.monotonic()
        try:
            response = requests.post(_OLLAMA_URL, json=payload, timeout=_TIMEOUT_SEC)
            elapsed = time.monotonic() - t0
            log.info("LLM ← state=%s attempt=%d status=%d elapsed=%.1fs",
                     state_name, attempt, response.status_code, elapsed)
            response.raise_for_status()
            raw = response.json().get("response", "")
            log.debug("LLM raw response: %r", raw)
            return _parse_json(raw)
        except (requests.RequestException, ValueError) as exc:
            elapsed = time.monotonic() - t0
            last_exc = exc
            if attempt >= _MAX_RETRIES:
                break
            sleep_s = _BACKOFF_SEC * attempt
            log.warning(
                "LLM call failed for state=%s attempt=%d/%d after %.1fs: %s: %s; retrying in %.1fs",
                state_name, attempt, _MAX_RETRIES, elapsed, type(exc).__name__, exc, sleep_s,
            )
            time.sleep(sleep_s)

    raise RuntimeError(f"LLM call failed for state='{state_name}' after {_MAX_RETRIES} attempts") from last_exc
