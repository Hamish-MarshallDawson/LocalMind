from __future__ import annotations

import logging
from pathlib import Path

from localmind.config import AppConfig
from localmind.models.manager import ModelManager

from .chunker import Chunk, chunk_text
from .handlers import HANDLER_MAP
from .types import Document, IngestResult

logger = logging.getLogger(__name__)


class IngestPipeline:
    def __init__(self, config: AppConfig, model_manager: ModelManager):
        self.config = config
        self.model_manager = model_manager

    def ingest_file(self, path: Path) -> IngestResult:
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")

        ext = path.suffix.lower()
        if ext not in self.config.ingest.supported_extensions:
            raise ValueError(f"Unsupported file type: {ext}")

        size_mb = path.stat().st_size / 1024 / 1024
        if size_mb > self.config.ingest.max_file_size_mb:
            raise ValueError(f"File too large: {size_mb:.1f} MB (max {self.config.ingest.max_file_size_mb} MB)")

        handler = HANDLER_MAP.get(ext)
        if handler is None:
            raise ValueError(f"No handler for: {ext}")

        logger.info("Ingesting %s (%s, %.1f MB)", path.name, ext, size_mb)
        document = handler(path, model_manager=self.model_manager)

        chunks = self._chunk_document(document)
        logger.info("Ingested %s: %d pages, %d chunks", path.name, len(document.pages), len(chunks))

        return IngestResult(
            source=path,
            document=document,
            num_pages=len(document.pages),
            num_chunks=len(chunks),
        )

    def ingest_directory(self, directory: Path) -> list[IngestResult]:
        directory = Path(directory)
        results = []
        for path in sorted(directory.rglob("*")):
            if path.is_file() and path.suffix.lower() in self.config.ingest.supported_extensions:
                try:
                    result = self.ingest_file(path)
                    results.append(result)
                except Exception as e:
                    logger.error("Failed to ingest %s: %s", path, e)
        return results

    def process_to_chunks(self, path: Path, source_name: str | None = None) -> list[Chunk]:
        path = Path(path)
        ext = path.suffix.lower()
        handler = HANDLER_MAP.get(ext)
        if handler is None:
            raise ValueError(f"No handler for: {ext}")

        document = handler(path, model_manager=self.model_manager)
        # Keep the original too: search works on text chunks, but editing (a LaTeX CV, say) needs
        # the real file, which the open_document tool reads.
        from localmind.tools.documents import keep_original

        keep_original(self.config, path, source_name or path.name)
        return self._chunk_document(document, source_name or path.name)

    def _chunk_document(self, document: Document, source_name: str | None = None) -> list[Chunk]:
        # Store the bare filename so citations read "cv.pdf p.2" rather than a temp upload path.
        source = source_name or Path(document.source).name
        all_chunks: list[Chunk] = []
        for page in document.pages:
            chunks = chunk_text(
                text=page.text,
                source=source,
                page_number=page.page_number,
                chunk_size=self.config.rag.chunk_size,
                chunk_overlap=self.config.rag.chunk_overlap,
                metadata=document.metadata,
            )
            all_chunks.extend(chunks)
        return all_chunks
