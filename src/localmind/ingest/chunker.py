from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Chunk:
    text: str
    source: str
    page_number: int
    chunk_index: int
    metadata: dict


def chunk_text(
    text: str,
    source: str,
    page_number: int = 1,
    chunk_size: int = 512,
    chunk_overlap: int = 64,
    metadata: dict | None = None,
) -> list[Chunk]:
    if not text.strip():
        return []

    words = text.split()
    chunks: list[Chunk] = []
    start = 0
    idx = 0

    while start < len(words):
        end = start + chunk_size
        chunk_words = words[start:end]
        chunk_text = " ".join(chunk_words)

        chunks.append(Chunk(
            text=chunk_text,
            source=source,
            page_number=page_number,
            chunk_index=idx,
            metadata=metadata or {},
        ))

        start += chunk_size - chunk_overlap
        idx += 1

    return chunks
