"""Run all questions through the agent, score answers, save results."""
from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path

# Force unbuffered output so Docker streams logs in real time
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stderr,
)
log = logging.getLogger(__name__)

import agent
import scorer
from tools import _load_graph

_QUESTIONS_PATH = Path(__file__).parent / "questions.json"
_RESULTS_PATH = Path(__file__).parent.parent / "outputs" / "eval_results.json"


def _banner(msg: str) -> None:
    print(f"\n>>> {msg}", flush=True)


def main() -> None:
    _banner("Loading knowledge graph...")
    t_load = time.time()
    try:
        _load_graph()
    except FileNotFoundError as exc:
        log.error("%s", exc)
        sys.exit(1)
    _banner(f"Graph loaded in {time.time() - t_load:.1f}s")

    questions = json.loads(_QUESTIONS_PATH.read_text())
    _banner(f"Starting eval: {len(questions)} questions  model={agent._MODEL}")

    results = []
    total = len(questions)
    for idx, q in enumerate(questions, start=1):
        print(f"\n--- Q{q['id']} [{idx}/{total}]: {q['question']}", flush=True)
        t0 = time.time()
        outcome = agent.run(q["question"])
        elapsed = round(time.time() - t0, 2)

        score_result = scorer.score(q, outcome["answer"])
        status = "PASS" if score_result["correct"] else "FAIL"

        print(f"    [{status}] answer={outcome['answer']}", flush=True)
        print(f"    detail={score_result['detail']}  turns={len(outcome['turns'])}  time={elapsed}s", flush=True)

        results.append({
            "id": q["id"],
            "question": q["question"],
            "expected": q.get("expected"),
            "expected_type": q.get("expected_type", "string"),
            "answer": outcome["answer"],
            "correct": score_result["correct"],
            "score_detail": score_result["detail"],
            "turns": outcome["turns"],
            "elapsed_s": elapsed,
        })
        print(f"    Progress: {idx}/{total} done", flush=True)

    summary = scorer.summarise(results)
    output = {"summary": summary, "results": results}
    _RESULTS_PATH.parent.mkdir(exist_ok=True)
    _RESULTS_PATH.write_text(json.dumps(output, indent=2))

    print("\n" + "=" * 52, flush=True)
    print(f"  Score: {summary['score']}  |  Accuracy: {summary['accuracy']:.1%}", flush=True)
    print(f"  By type: {summary['by_type']}", flush=True)
    print("=" * 52, flush=True)
    for r in results:
        mark = "PASS" if r["correct"] else "FAIL"
        print(f"  [{mark}] Q{r['id']} [{r['expected_type']}]: {r['question']}", flush=True)
        print(f"         Answer: {r['answer']}", flush=True)
        print(f"         Detail: {r['score_detail']}", flush=True)
    print("=" * 52 + "\n", flush=True)
    log.info("Results saved to %s", _RESULTS_PATH)


if __name__ == "__main__":
    main()
