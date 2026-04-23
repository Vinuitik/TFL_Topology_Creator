"""Run all questions through the agent, score answers, save results."""
from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
log = logging.getLogger(__name__)

import agent
import scorer
from tools import _load_graph

_QUESTIONS_PATH = Path(__file__).parent / "questions.json"
_RESULTS_PATH = Path(__file__).parent.parent / "outputs" / "eval_results.json"


def main() -> None:
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

        score_result = scorer.score(q, outcome["answer"])

        record = {
            "id": q["id"],
            "question": q["question"],
            "expected": q.get("expected"),
            "expected_type": q.get("expected_type", "string"),
            "answer": outcome["answer"],
            "correct": score_result["correct"],
            "score_detail": score_result["detail"],
            "turns": outcome["turns"],
            "elapsed_s": elapsed,
        }
        results.append(record)
        status = "PASS" if score_result["correct"] else "FAIL"
        log.info(
            "Q%s [%s] answer=%s | %s (%.1fs, %d turns)",
            q["id"],
            status,
            outcome["answer"],
            score_result["detail"],
            elapsed,
            len(outcome["turns"]),
        )

    summary = scorer.summarise(results)

    output = {"summary": summary, "results": results}
    _RESULTS_PATH.parent.mkdir(exist_ok=True)
    _RESULTS_PATH.write_text(json.dumps(output, indent=2))
    log.info("Results saved to %s", _RESULTS_PATH)

    print("\n" + "=" * 50)
    print(f"  Score: {summary['score']}  |  Accuracy: {summary['accuracy']:.1%}")
    print(f"  By type: {summary['by_type']}")
    print("=" * 50)
    for r in results:
        mark = "✓" if r["correct"] else "✗"
        print(f"  {mark} Q{r['id']} [{r['expected_type']}]: {r['question']}")
        print(f"      Answer:  {r['answer']}")
        print(f"      Detail:  {r['score_detail']}")
    print("=" * 50 + "\n")


if __name__ == "__main__":
    main()
