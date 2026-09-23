from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image


@dataclass
class Document:
    source: str
    text: str
    pages: list[PageContent] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


@dataclass
class PageContent:
    page_number: int
    text: str
    image: Image.Image | None = None


@dataclass
class IngestResult:
    source: Path
    document: Document
    num_pages: int
    num_chunks: int
