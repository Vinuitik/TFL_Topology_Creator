from __future__ import annotations

import os
import re
from typing import List

CHUNK_MAX_WORDS: int = int(os.getenv("CHUNK_MAX_WORDS"))
OVERLAP_SENTENCES: int = 2


def split_sentences(text: str) -> List[str]:
    """Split on sentence-ending punctuation followed by whitespace + capital letter."""
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z])", text.strip())
    return [s.strip() for s in parts if s.strip()]


def make_chunks(sentences: List[str], max_words: int = CHUNK_MAX_WORDS) -> List[List[str]]:
    """Group sentences into chunks of at most max_words. Single oversized sentences get their own chunk."""
    chunks: List[List[str]] = []
    current: List[str] = []
    count = 0
    for sent in sentences:
        w = len(sent.split())
        if count + w > max_words and current:
            chunks.append(current)
            current = []
            count = 0
        current.append(sent)
        count += w
    if current:
        chunks.append(current)
    return chunks
