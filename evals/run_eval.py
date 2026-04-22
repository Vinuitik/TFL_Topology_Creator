"""CLI: run all questions through the agent, save results to outputs/eval_results.json."""
from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
log = logging.getLogger(__name__)

import agent
from tools import _load_graph

_QUESTIONS_PATH = Path(__file__).parent / "questions.json"
_RESULTS_PATH = Path(__file__).parent.parent / "outputs" / "eval_results.json"


def main() -> None:
    # Fail fast if graph not ready
    try:
        _load_graph()
    except FileNotFoundError as exc:
        log.error("%s", exc)
        sys.exit(1)

    questions = json.loads(_QUESTIONS_PATH.read_text())
    log.info("Running %d questions against model %s", len(questions), agent._MODEL)

    results = []
    for q in questions:
        log.info("Q%s: %s", q["id"], q["question"])
        t0 = time.time()
        outcome = agent.run(q["question"])
        elapsed = round(time.time() - t0, 2)
        record = {
            "id": q["id"],
            "question": q["question"],
            "expected": q.get("expected"),
            "answer": outcome["answer"],
            "turns": outcome["turns"],
            "elapsed_s": elapsed,
        }
        results.append(record)
        log.info("Q%s answer: %s (%.1fs, %d turns)",
                 q["id"], outcome["answer"], elapsed, len(outcome["turns"]))

    _RESULTS_PATH.parent.mkdir(exist_ok=True)
    _RESULTS_PATH.write_text(json.dumps(results, indent=2))
    log.info("Results saved to %s", _RESULTS_PATH)

    answered = sum(1 for r in results if r["answer"])
    log.info("Answered %d/%d questions", answered, len(results))


if __name__ == "__main__":
    main()
