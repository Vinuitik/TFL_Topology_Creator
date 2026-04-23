"""Build a lightweight JSON vector index from data_sources."""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from config import COMPLETION_DIR, DATA_SOURCES_DIR, RAG_CHUNK_CHARS, RAG_CHUNK_OVERLAP
from utils import embed, normalize_ws

log = logging.getLogger(__name__)


def _chunk_text(text: str, size: int, overlap: int) -> list[str]:
    text = normalize_ws(text)
    if not text:
        return []
    chunks = []
    step = max(1, size - overlap)
    for start in range(0, len(text), step):
        piece = text[start : start + size]
        if piece:
            chunks.append(piece)
        if start + size >= len(text):
            break
    return chunks


def _read_source(path: Path) -> str:
    if path.suffix.lower() == ".json":
        data = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
        return json.dumps(data, ensure_ascii=True)
    return path.read_text(encoding="utf-8", errors="ignore")


def run() -> Path:
    COMPLETION_DIR.mkdir(parents=True, exist_ok=True)
    out = COMPLETION_DIR / "rag_index.json"

    records = []
    src_files = sorted(
        [
            p
            for p in DATA_SOURCES_DIR.glob("*")
            if p.is_file() and p.suffix.lower() in {".txt", ".json", ".csv", ".tsv"}
        ]
    )

    total_files = len(src_files)
    log.info("RAG build: %d source file(s)", total_files)
    all_started = time.time()
    for file_idx, src in enumerate(src_files, start=1):
        file_started = time.time()
        log.info("RAG build [%d/%d] reading %s", file_idx, total_files, src.name)
        raw = _read_source(src)
        chunks = _chunk_text(raw, RAG_CHUNK_CHARS, RAG_CHUNK_OVERLAP)
        log.info("RAG build [%d/%d] %s -> %d chunk(s)", file_idx, total_files, src.name, len(chunks))
        before_count = len(records)
        for idx, chunk in enumerate(chunks):
            vec = embed(chunk)
            if not vec:
                continue
            records.append(
                {
                    "id": f"{src.name}:{idx}",
                    "file": str(src.relative_to(DATA_SOURCES_DIR)),
                    "chunk_index": idx,
                    "text": chunk,
                    "embedding": vec,
                }
            )
            if (idx + 1) % 25 == 0:
                log.info(
                    "RAG build [%d/%d] %s progress: %d/%d chunks",
                    file_idx,
                    total_files,
                    src.name,
                    idx + 1,
                    len(chunks),
                )

        added_for_file = len(records) - before_count
        log.info(
            "RAG build [%d/%d] %s done: indexed=%d (%.2fs)",
            file_idx,
            total_files,
            src.name,
            added_for_file,
            time.time() - file_started,
        )

    out.write_text(json.dumps({"records": records}, ensure_ascii=True), encoding="utf-8")
    log.info("RAG build complete: %d chunks -> %s (%.2fs)", len(records), out, time.time() - all_started)
    return out


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    run()
