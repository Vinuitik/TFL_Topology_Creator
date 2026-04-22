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
_TEMPERATURE = float(os.getenv("OLLAMA_TEMPERATURE", "0.3"))
_SEED = int(os.getenv("OLLAMA_SEED", "42"))
_MAX_RETRIES = int(os.getenv("OLLAMA_MAX_RETRIES", "3"))


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

    # attempt 3: fix truncated JSON by closing open brackets (handles stream cutoff)
    stripped = raw.strip()
    if stripped.startswith("{"):
        open_braces = stripped.count("{") - stripped.count("}")
        open_brackets = stripped.count("[") - stripped.count("]")
        candidate = stripped.rstrip(", \t\n\r")
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
    timeout: float | None = None,
) -> Any:
    prompt_path = _find_latest_prompt(state_name)
    log.debug("Using prompt %s", prompt_path.name)

    full_prompt = prompt_path.read_text(encoding="utf-8") + params
    effective_model = model or _MODEL
    effective_timeout = timeout or _TIMEOUT_SEC

    options = {"temperature": _TEMPERATURE, "seed": _SEED, "repeat_penalty": 1.15}
    if extra_options:
        options.update(extra_options)

    payload = {
        "model": effective_model,
        "prompt": full_prompt,
        "stream": True,
        "format": "json",
        "options": options,
    }

<<<<<<< HEAD
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
            if response.status_code != 200:
                log.error("Ollama error response: %s", response.text)
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
=======
    log.debug("LLM → state=%s model=%s prompt_chars=%d timeout=%.0fs",
              state_name, effective_model, len(full_prompt), effective_timeout)
>>>>>>> reasoning-ontology-pipeline-v2

    for attempt in range(1, _MAX_RETRIES + 1):
        seed = _SEED + (attempt - 1)
        payload["options"] = {**options, "seed": seed}

        t0 = time.monotonic()
        accumulated = ""
        timed_out = False

        try:
            with requests.post(
                _OLLAMA_URL, json=payload, stream=True,
                timeout=effective_timeout,
            ) as response:
                response.raise_for_status()
                deadline = t0 + effective_timeout
                for line in response.iter_lines():
                    if time.monotonic() > deadline:
                        timed_out = True
                        log.warning("LLM stream timeout after %.0fs for state=%s attempt=%d — parsing partial",
                                    effective_timeout, state_name, attempt)
                        break
                    if line:
                        chunk = json.loads(line)
                        accumulated += chunk.get("response", "")
                        if chunk.get("done"):
                            break
        except requests.exceptions.Timeout:
            timed_out = True
            log.warning("LLM connect timeout for state=%s attempt=%d — parsing partial", state_name, attempt)
        except requests.RequestException as exc:
            raise RuntimeError(f"LLM request failed for state='{state_name}': {exc}") from exc

        elapsed = time.monotonic() - t0
        log.debug("LLM ← state=%s attempt=%d seed=%d elapsed=%.1fs partial=%s",
                  state_name, attempt, seed, elapsed, timed_out)

        try:
            return _parse_json(accumulated)
        except ValueError:
            if attempt < _MAX_RETRIES:
                log.warning("LLM bad JSON for state=%s attempt=%d seed=%d — retrying with seed=%d",
                            state_name, attempt, seed, seed + 1)
            else:
                raise
