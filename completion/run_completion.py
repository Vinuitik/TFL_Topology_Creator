"""Orchestrate completion pipeline: build RAG -> gaps -> proposals -> apply."""
from __future__ import annotations

import logging
import time

import apply_fills
import build_rag
import find_gaps
import propose_fills
from config import KG_INPUT_PATH, KG_OUTPUT_PATH


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    log = logging.getLogger(__name__)

    log.info("=== KG Completion ===")
    log.info("Input graph: %s", KG_INPUT_PATH)
    log.info("Output graph: %s", KG_OUTPUT_PATH)

    t0 = time.time()
    log.info("[1/4] Build RAG index start")
    idx = build_rag.run()
    log.info("[1/4] Build RAG index done (%.2fs)", time.time() - t0)

    t1 = time.time()
    log.info("[2/4] Detect gaps start")
    gaps = find_gaps.run()
    log.info("[2/4] Detect gaps done (%.2fs)", time.time() - t1)

    t2 = time.time()
    log.info("[3/4] Generate proposals start")
    props = propose_fills.run()
    log.info("[3/4] Generate proposals done (%.2fs)", time.time() - t2)

    t3 = time.time()
    log.info("[4/4] Apply proposals start")
    out_ttl, report = apply_fills.run()
    log.info("[4/4] Apply proposals done (%.2fs)", time.time() - t3)

    print("\n=== Completion Complete ===")
    print(f"RAG index:  {idx}")
    print(f"Gaps:       {gaps}")
    print(f"Proposals:  {props}")
    print(f"Output TTL: {out_ttl}")
    print(f"Report:     {report}")


if __name__ == "__main__":
    main()
