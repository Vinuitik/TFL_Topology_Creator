"""Build a lightweight JSON vector index from data_sources."""
from __future__ import annotations

import json
import logging
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

    log.info("RAG build: %d source file(s)", len(src_files))
    for src in src_files:
        raw = _read_source(src)
        chunks = _chunk_text(raw, RAG_CHUNK_CHARS, RAG_CHUNK_OVERLAP)
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

    out.write_text(json.dumps({"records": records}, ensure_ascii=True), encoding="utf-8")
    log.info("RAG build complete: %d chunks -> %s", len(records), out)
    return out


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    run()
