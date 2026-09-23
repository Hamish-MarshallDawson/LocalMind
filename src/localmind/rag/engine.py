from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath

import lancedb
import pyarrow as pa
from lancedb.index import FTS

from localmind.config import AppConfig
from localmind.ingest.chunker import Chunk
from localmind.models.manager import ModelManager

from .sections import KnowledgeSections

logger = logging.getLogger(__name__)

SCHEMA = pa.schema([
    pa.field("text", pa.utf8()),
    pa.field("source", pa.utf8()),
    pa.field("page_number", pa.int32()),
    pa.field("chunk_index", pa.int32()),
    pa.field("metadata", pa.utf8()),
    pa.field("vector", pa.list_(pa.float32(), 768)),
])


RRF_K = 60  # standard Reciprocal Rank Fusion constant

# PDF extraction often turns bullet glyphs into C1 control characters (\x80-\x9f).
# Also Symbol-font bullets from Word exports (U+F0B7, U+F0A7) and square/round bullets.
# Kept as escapes so the pattern survives editors and shells that mangle encodings.
_CONTROL_CHARS = re.compile("[\\x80-\\x9f\\uf0b7\\uf0a7\\u25aa\\u25cf]")
BULLET = "\u2022"


def _tidy(text: str) -> str:
    return _CONTROL_CHARS.sub(BULLET, str(text or ""))


def _fts_query(query: str) -> str:
    """Strip query-parser syntax (quotes, colons, parentheses) that makes keyword search throw."""
    words = re.sub(r"[^\w\s+#]", " ", query).split()
    return " ".join(w for w in words if w.upper() not in {"AND", "OR", "NOT"})


def _as_limit(value, default: int) -> int:
    """Models routinely send numbers as strings ("5") or floats; accept anything sensible."""
    try:
        return max(1, min(int(float(value)), 50))
    except (TypeError, ValueError):
        return default


def _sql_str(value: str) -> str:
    """Quote a string literal for LanceDB filters. Double quotes mean a column name there."""
    return "'" + str(value).replace("'", "''") + "'"


@dataclass
class SearchResult:
    text: str
    source: str
    page_number: int
    score: float


class RAGEngine:
    TABLE_NAME = "documents"

    def __init__(self, config: AppConfig, model_manager: ModelManager):
        self.config = config
        self.model_manager = model_manager

        db_path = Path(config.rag.db_path)
        db_path.mkdir(parents=True, exist_ok=True)
        self.db = lancedb.connect(str(db_path))
        # Which section each document belongs to, and which sections every chat can see.
        self.sections = KnowledgeSections(db_path.parent / "kb_sections.json")

        self._ensure_table()

    def _ensure_table(self) -> None:
        listed = self.db.list_tables()
        existing = list(getattr(listed, "tables", listed))
        if self.TABLE_NAME not in existing:
            self.db.create_table(self.TABLE_NAME, schema=SCHEMA)
            logger.info("Created LanceDB table: %s", self.TABLE_NAME)
        else:
            self._normalise_source_names()
            self._remove_duplicate_chunks()

    def _remove_duplicate_chunks(self) -> None:
        """Older versions appended a document again when it was re-uploaded. Keep one copy."""
        table = self.db.open_table(self.TABLE_NAME)
        if table.count_rows() == 0:
            return
        rows = table.to_arrow().to_pylist()
        seen: set[tuple] = set()
        affected: dict[str, list[dict]] = {}
        for row in rows:
            key = (row["source"], row["page_number"], row["chunk_index"], row["text"])
            if key in seen:
                affected.setdefault(row["source"], [])
            else:
                seen.add(key)
        if not affected:
            return
        for source in affected:
            keep, kept_keys = [], set()
            for row in rows:
                key = (row["source"], row["page_number"], row["chunk_index"], row["text"])
                if row["source"] == source and key not in kept_keys:
                    kept_keys.add(key)
                    keep.append(row)
            table.delete(f"source = {_sql_str(source)}")
            table.add(keep)
            logger.info("Removed duplicate chunks from %s (kept %d)", source, len(keep))
        self._rebuild_fts_index()

    def _normalise_source_names(self) -> None:
        """Rewrite sources stored as full paths (old Gradio temp uploads) to bare filenames."""
        table = self.db.open_table(self.TABLE_NAME)
        if table.count_rows() == 0:
            return
        sources = table.to_arrow().column("source").unique().to_pylist()
        for source in sources:
            if source and ("\\" in source or "/" in source):
                name = PureWindowsPath(source).name  # splits on both \ and /
                table.update(where=f"source = {_sql_str(source)}", values={"source": name})
                logger.info("Renamed knowledge-base source %s -> %s", source, name)

    def _embed_texts(self, texts: list[str]) -> list[list[float]]:
        model = self.model_manager.get_embedding_model()
        embeddings = model.encode(texts, show_progress_bar=False, normalize_embeddings=True)
        return embeddings.tolist()

    def _embed_query(self, query: str) -> list[float]:
        # bge-*-v1.5 retrieves noticeably better when short queries carry its instruction prefix;
        # passages are embedded without it.
        model = self.model_manager.get_embedding_model()
        prefixed = f"{self.config.models.embedding.query_prefix}{query}"
        embedding = model.encode(prefixed, show_progress_bar=False, normalize_embeddings=True)
        return embedding.tolist()

    def add_chunks(self, chunks: list[Chunk]) -> int:
        if not chunks:
            return 0

        import json

        texts = [c.text for c in chunks]
        vectors = self._embed_texts(texts)

        records = [
            {
                "text": chunk.text,
                "source": chunk.source,
                "page_number": chunk.page_number,
                "chunk_index": chunk.chunk_index,
                "metadata": json.dumps(chunk.metadata),
                "vector": vector,
            }
            for chunk, vector in zip(chunks, vectors)
        ]

        table = self.db.open_table(self.TABLE_NAME)
        # Re-uploading a document replaces it rather than indexing a second copy.
        for source in {c.source for c in chunks}:
            table.delete(f"source = {_sql_str(source)}")
        table.add(records)
        self._rebuild_fts_index()

        logger.info("Added %d chunks to vector store", len(records))
        return len(records)

    def search(self, query: str, top_k: int | None = None) -> list[SearchResult]:
        """Vector-only search."""
        top_k = _as_limit(top_k, self.config.rag.top_k)
        query = (query or "").strip()
        table = self.db.open_table(self.TABLE_NAME)
        if not query or table.count_rows() == 0:
            return []
        rows = table.search(self._embed_query(query)).limit(top_k).to_list()
        return [self._result(row, 1.0 / (1.0 + float(row.get("_distance", 0.0)))) for row in rows]

    def _allowed(self, scope: str | None) -> set[str] | None:
        """Documents a search with this scope may return (None: all of them)."""
        return self.sections.visible_sources(scope or "", self.list_sources())

    def search_hybrid(self, query: str, top_k: int | None = None, scope: str | None = None) -> list[SearchResult]:
        """Vector + keyword search fused with Reciprocal Rank Fusion.

        RRF scores each chunk by its rank in both lists (1 / (k + rank)), so a chunk that is
        decent in both beats one that is top of only one. Scores are normalised so 1.0 means
        "ranked first by both retrievers".
        """
        top_k = _as_limit(top_k, self.config.rag.top_k)
        query = (query or "").strip()
        table = self.db.open_table(self.TABLE_NAME)
        if not query or table.count_rows() == 0:
            return []

        allowed = self._allowed(scope)
        if allowed is not None and not allowed:
            return []  # nothing in the sections this chat may see
        where = None if allowed is None else "source IN (" + ", ".join(_sql_str(s) for s in sorted(allowed)) + ")"

        pool = max(top_k * 4, 20)
        vector = table.search(self._embed_query(query))
        if where:
            vector = vector.where(where, prefilter=True)
        ranked_lists = [vector.limit(pool).to_list()]

        keywords = _fts_query(query)
        if keywords and self._ensure_fts_index(table):
            try:
                fts = table.search(keywords, query_type="fts")
                if where:
                    fts = fts.where(where, prefilter=True)
                ranked_lists.append(fts.limit(pool).to_list())
            except Exception as e:  # noqa: BLE001 - keyword search is a bonus, never fatal
                logger.warning("Keyword search failed for %r: %s", keywords, e)
        if allowed is not None:
            # Checked again row by row: a section boundary must hold even if a filter misbehaves.
            ranked_lists = [[row for row in ranked if row["source"] in allowed] for ranked in ranked_lists]

        fused: dict[tuple, float] = {}
        rows: dict[tuple, dict] = {}
        for ranked in ranked_lists:
            seen_here: set[tuple] = set()
            for rank, row in enumerate(ranked):
                key = (row["source"], row["page_number"], row["chunk_index"], row["text"])
                if key in seen_here:
                    continue  # a duplicate row must not count twice
                seen_here.add(key)
                fused[key] = fused.get(key, 0.0) + 1.0 / (RRF_K + rank + 1)
                rows.setdefault(key, row)

        best_possible = len(ranked_lists) / (RRF_K + 1)
        order = sorted(fused, key=fused.get, reverse=True)[:top_k]
        return [self._result(rows[key], fused[key] / best_possible) for key in order]

    def _result(self, row: dict, score: float) -> SearchResult:
        return SearchResult(
            text=_tidy(row["text"]),
            source=row["source"],
            page_number=int(row["page_number"]),
            score=round(score, 4),
        )

    def _ensure_fts_index(self, table) -> bool:
        """Build the keyword index once, not on every query (each rebuild adds a table version)."""
        try:
            if any(getattr(ix, "index_type", "") == "FTS" for ix in table.list_indices()):
                return True
            table.create_index("text", config=FTS(), replace=True)
            return True
        except Exception as e:  # noqa: BLE001
            logger.warning("Full-text index unavailable, using vector search only: %s", e)
            return False

    def _rebuild_fts_index(self) -> None:
        table = self.db.open_table(self.TABLE_NAME)
        if table.count_rows() == 0:
            return
        try:
            table.create_index("text", config=FTS(), replace=True)
        except Exception as e:  # noqa: BLE001
            logger.warning("Could not rebuild full-text index: %s", e)

    def delete_source(self, source: str) -> int:
        table = self.db.open_table(self.TABLE_NAME)
        before = table.count_rows()
        table.delete(f"source = {_sql_str(source)}")
        after = table.count_rows()
        deleted = before - after
        logger.info("Deleted %d chunks from source: %s", deleted, source)
        self.sections.forget(source)
        self._rebuild_fts_index()
        return deleted

    def list_sources(self) -> list[str]:
        table = self.db.open_table(self.TABLE_NAME)
        if table.count_rows() == 0:
            return []
        df = table.to_pandas()
        return sorted(df["source"].unique().tolist())

    def count(self) -> int:
        table = self.db.open_table(self.TABLE_NAME)
        return table.count_rows()
