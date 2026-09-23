"""SQLite-backed conversation store.

Keeps two things per conversation: the display history the chat widget renders (including
tool-call bubbles) and the agent transcript that actually feeds the model. Both are needed -
reloading a chat should restore what the user saw *and* the evidence the model was working from.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
    id          TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    created_at  REAL NOT NULL,
    updated_at  REAL NOT NULL,
    display     TEXT NOT NULL DEFAULT '[]',
    transcript  TEXT NOT NULL DEFAULT '[]'
);
CREATE INDEX IF NOT EXISTS idx_conversations_updated ON conversations(updated_at DESC);
"""

DEFAULT_TITLE = "New chat"


@dataclass
class Conversation:
    id: str
    title: str
    created_at: float
    updated_at: float


def _json_safe(value: Any) -> Any:
    """Strip anything not JSON-serialisable (PIL images, mostly) from message content."""
    if isinstance(value, dict):
        if value.get("type") == "image":
            return {"type": "text", "text": "[image attached]"}
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def title_from_message(text: str, limit: int = 48) -> str:
    text = " ".join(str(text or "").split())
    if not text:
        return DEFAULT_TITLE
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


class ConversationStore:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(SCHEMA)
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(conversations)")}
            if "settings" not in columns:
                conn.execute("ALTER TABLE conversations ADD COLUMN settings TEXT NOT NULL DEFAULT '{}'")

    def get_settings(self, cid: str | None) -> dict:
        """Per-chat choices: model, thinking and forced-tool toggles, last context measurement."""
        if not cid:
            return {}
        with self._connect() as conn:
            row = conn.execute("SELECT settings FROM conversations WHERE id = ?", (cid,)).fetchone()
        try:
            return json.loads(row["settings"]) if row else {}
        except json.JSONDecodeError:
            return {}

    def update_settings(self, cid: str | None, **changes) -> dict:
        if not cid:
            return {}
        settings = {**self.get_settings(cid), **changes}
        with self._connect() as conn:
            conn.execute("UPDATE conversations SET settings=? WHERE id=?", (json.dumps(_json_safe(settings)), cid))
        return settings

    def _connect(self) -> sqlite3.Connection:
        # A connection per operation keeps this safe across Gradio's handler threads.
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def create(self, title: str = DEFAULT_TITLE, cid: str | None = None) -> str:
        """A new, empty chat. `cid` lets the gateway name a chat it started while this PC was off."""
        cid = cid or uuid.uuid4().hex[:12]
        now = time.time()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO conversations (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (cid, title, now, now),
            )
        logger.debug("Created conversation %s", cid)
        return cid

    def list(self) -> list[Conversation]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, title, created_at, updated_at FROM conversations ORDER BY updated_at DESC"
            ).fetchall()
        return [Conversation(**dict(row)) for row in rows]

    def get(self, cid: str) -> Conversation | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, title, created_at, updated_at FROM conversations WHERE id = ?", (cid,)
            ).fetchone()
        return Conversation(**dict(row)) if row else None

    def load(self, cid: str) -> tuple[list[dict], list[dict]]:
        """Return (display_history, agent_transcript)."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT display, transcript FROM conversations WHERE id = ?", (cid,)
            ).fetchone()
        if row is None:
            return [], []
        try:
            return json.loads(row["display"]), json.loads(row["transcript"])
        except json.JSONDecodeError:
            logger.warning("Corrupt payload for conversation %s; starting empty", cid)
            return [], []

    def save(
        self,
        cid: str,
        display: list[dict],
        transcript: list[dict],
        title: str | None = None,
    ) -> None:
        payload = (
            json.dumps(_json_safe(display)),
            json.dumps(_json_safe(transcript)),
            time.time(),
        )
        with self._connect() as conn:
            if title:
                conn.execute(
                    "UPDATE conversations SET display=?, transcript=?, updated_at=?, title=? WHERE id=?",
                    (*payload, title, cid),
                )
            else:
                conn.execute(
                    "UPDATE conversations SET display=?, transcript=?, updated_at=? WHERE id=?",
                    (*payload, cid),
                )

    def touch(self, cid: str) -> None:
        """Mark a conversation as just used so it sorts to the top."""
        with self._connect() as conn:
            conn.execute("UPDATE conversations SET updated_at=? WHERE id=?", (time.time(), cid))

    def rename(self, cid: str, title: str) -> None:
        with self._connect() as conn:
            conn.execute("UPDATE conversations SET title=? WHERE id=?", (title or DEFAULT_TITLE, cid))

    def delete(self, cid: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM conversations WHERE id = ?", (cid,))
        logger.debug("Deleted conversation %s", cid)

    def is_empty(self, cid: str) -> bool:
        display, _ = self.load(cid)
        return not display
