"""Orchestrate completion pipeline: build RAG -> gaps -> proposals -> apply."""
from __future__ import annotations

import logging

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
    idx = build_rag.run()
    gaps = find_gaps.run()
    props = propose_fills.run()
    out_ttl, report = apply_fills.run()

    print("\n=== Completion Complete ===")
    print(f"RAG index:  {idx}")
    print(f"Gaps:       {gaps}")
    print(f"Proposals:  {props}")
    print(f"Output TTL: {out_ttl}")
    print(f"Report:     {report}")


if __name__ == "__main__":
    main()
