"""What the gateway remembers while the PC is off: its last report, copies of recent chats, and
the messages waiting to be delivered."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    updated_at REAL NOT NULL,
    data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS deleted (id TEXT PRIMARY KEY, at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    text TEXT NOT NULL,
    options TEXT NOT NULL,
    state TEXT NOT NULL,
    detail TEXT,
    error TEXT,
    reply TEXT NOT NULL DEFAULT '[]',
    created REAL NOT NULL,
    updated REAL NOT NULL
);
"""

ACTIVE = ("queued", "waking", "starting", "sending", "running")


class GatewayStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._connect() as conn:
            conn.executescript(SCHEMA)
            # A gateway restart mid-delivery: those jobs will be picked up again from the start.
            conn.execute("UPDATE jobs SET state='queued', detail=NULL WHERE state IN ('waking','starting','sending','running')")

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    # ------------------------------------------------------------------ the PC's reports
    def save_report(self, report: dict) -> None:
        body = {k: v for k, v in report.items() if k not in ("conversations", "conversation_ids")}
        record = {"report": body, "received_at": time.time()}
        with self._lock, self._connect() as conn:
            conn.execute("INSERT OR REPLACE INTO kv VALUES ('pc', ?)", (json.dumps(record),))
            gone = {r["id"] for r in conn.execute("SELECT id FROM deleted")}
            for conv in report.get("conversations") or []:
                if conv.get("id") not in gone:  # deleted here; the PC hasn't heard yet
                    self._upsert(conn, conv)
            known = report.get("conversation_ids")
            if isinstance(known, list):
                # Drop chats deleted on the PC, but keep ones started here that haven't reached it yet.
                waiting = {r["conversation_id"] for r in conn.execute(f"SELECT conversation_id FROM jobs WHERE state IN {ACTIVE}")}
                keep = set(known) | waiting
                for row in conn.execute("SELECT id FROM conversations").fetchall():
                    if row["id"] not in keep:
                        conn.execute("DELETE FROM conversations WHERE id=?", (row["id"],))

    def last_report(self) -> tuple[dict | None, float | None]:
        with self._connect() as conn:
            row = conn.execute("SELECT value FROM kv WHERE key='pc'").fetchone()
        if not row:
            return None, None
        record = json.loads(row["value"])
        return record["report"], record["received_at"]

    # ------------------------------------------------------------------ chats
    @staticmethod
    def _upsert(conn, conv: dict) -> None:
        data = {"settings": conv.get("settings") or {}, "messages": conv.get("messages") or [], "context": conv.get("context")}
        conn.execute(
            "INSERT OR REPLACE INTO conversations (id, title, updated_at, data) VALUES (?, ?, ?, ?)",
            (conv["id"], conv.get("title") or "New chat", float(conv.get("updated_at") or time.time()), json.dumps(data)),
        )

    def upsert_conversation(self, conv: dict) -> None:
        with self._lock, self._connect() as conn:
            self._upsert(conn, conv)

    def ensure_conversation(self, cid: str, title: str) -> None:
        """A chat started here while the PC is off: list it now, fill it in once it's answered."""
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO conversations (id, title, updated_at, data) VALUES (?, ?, ?, ?)",
                (cid, title, time.time(), json.dumps({"settings": {}, "messages": []})),
            )
            conn.execute("UPDATE conversations SET updated_at=? WHERE id=?", (time.time(), cid))

    def delete_conversation(self, cid: str) -> None:
        """Forget a chat here now, and remember to delete it on the PC once it's reachable."""
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM conversations WHERE id=?", (cid,))
            conn.execute("INSERT OR REPLACE INTO deleted VALUES (?, ?)", (cid, time.time()))
            conn.execute(f"UPDATE jobs SET state='cancelled', detail=NULL WHERE conversation_id=? AND state IN {ACTIVE}", (cid,))

    def pending_deletions(self) -> list[str]:
        with self._connect() as conn:
            return [r["id"] for r in conn.execute("SELECT id FROM deleted ORDER BY at")]

    def deletion_done(self, cid: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM deleted WHERE id=?", (cid,))

    def set_context(self, cid: str, context: dict | None) -> None:
        if not context:
            return
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT data FROM conversations WHERE id=?", (cid,)).fetchone()
            if row:
                data = json.loads(row["data"])
                data["context"] = context
                conn.execute("UPDATE conversations SET data=? WHERE id=?", (json.dumps(data), cid))

    def list_conversations(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute("SELECT id, title, updated_at FROM conversations ORDER BY updated_at DESC").fetchall()
        return [dict(row) for row in rows]

    def get_conversation(self, cid: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM conversations WHERE id=?", (cid,)).fetchone()
        if not row:
            return None
        return {"id": row["id"], "title": row["title"], "updated_at": row["updated_at"], **json.loads(row["data"])}

    # ------------------------------------------------------------------ messages waiting for the PC
    def create_job(self, cid: str | None, text: str, options: dict, title: str) -> dict:
        cid = cid or uuid.uuid4().hex[:12]
        job_id = uuid.uuid4().hex[:12]
        now = time.time()
        self.ensure_conversation(cid, title)
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO jobs (id, conversation_id, text, options, state, created, updated) VALUES (?, ?, ?, ?, 'queued', ?, ?)",
                (job_id, cid, text, json.dumps(options), now, now),
            )
        return self.get_job(job_id)

    def update_job(self, job_id: str, **changes) -> dict:
        if "reply" in changes:
            changes["reply"] = json.dumps(changes["reply"])
        changes["updated"] = time.time()
        columns = ", ".join(f"{k}=?" for k in changes)
        with self._lock, self._connect() as conn:
            conn.execute(f"UPDATE jobs SET {columns} WHERE id=?", (*changes.values(), job_id))
        return self.get_job(job_id)

    def get_job(self, job_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        return _job(row) if row else None

    def jobs(self, *, active_only: bool = False, limit: int = 50) -> list[dict]:
        where = f"WHERE state IN {ACTIVE} OR state='failed'" if active_only else ""
        with self._connect() as conn:
            rows = conn.execute(f"SELECT * FROM jobs {where} ORDER BY created DESC LIMIT ?", (limit,)).fetchall()
        return [_job(row) for row in rows]

    def next_queued(self) -> dict | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE state='queued' ORDER BY created LIMIT 1").fetchone()
        return _job(row) if row else None


def _job(row) -> dict:
    job = dict(row)
    job["options"] = json.loads(job["options"])
    job["reply"] = json.loads(job["reply"] or "[]")
    return job
