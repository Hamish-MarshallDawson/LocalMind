"""A queue of tasks that run one after another, each in its own fresh chat.

The shape of a batch: one set of instructions ("Tailor my CV to this listing, as LaTeX, and
compile it") and several items (five job descriptions). Each item becomes a new chat whose first
message is the instructions followed by the item, so every task starts with an empty context
window: nothing from the Barclays CV leaks into the BlackRock one. Tasks run strictly in order,
survive a restart, and keep the PC from shutting itself down while any are waiting.
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS batches (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, instructions TEXT NOT NULL,
    options TEXT NOT NULL, created REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY, batch_id TEXT NOT NULL, position INTEGER NOT NULL, title TEXT NOT NULL,
    body TEXT NOT NULL, state TEXT NOT NULL, cid TEXT, error TEXT, started REAL, finished REAL
);
"""
WAITING, RUNNING, DONE, FAILED, CANCELLED = "waiting", "running", "done", "failed", "cancelled"
SEPARATOR = re.compile(r"^\s*-{3,}\s*$", re.M)


def split_items(text: str) -> list[dict]:
    """Items pasted into one box, separated by lines of three or more dashes."""
    items = []
    for block in SEPARATOR.split(text or ""):
        body = block.strip()
        if body:
            first = next(line.strip() for line in body.splitlines() if line.strip())
            items.append({"title": first[:70].rstrip(" :.,"), "body": body})
    return items


def item_from_file(path: Path, name: str | None = None) -> dict:
    """A job description (or anything else) from a file: its text becomes the item."""
    path = Path(path)
    name = name or path.name
    if path.suffix.lower() == ".pdf":
        import pymupdf

        with pymupdf.open(path) as doc:
            text = "\n".join(page.get_text() for page in doc)
    else:
        text = path.read_text(encoding="utf-8", errors="replace")
    return {"title": Path(name).stem[:70], "body": f"[{name}]\n{text.strip()}"}


def compose(instructions: str, body: str) -> str:
    return f"{instructions.strip()}\n\n---\n\n{body.strip()}" if instructions.strip() else body.strip()


class TaskQueue:
    def __init__(self, db_path: str | Path, turns, on_change: Callable[[], None] | None = None, poll: float = 0.5):
        self.path = Path(db_path)
        self.turns = turns
        self.on_change = on_change
        self.poll = poll
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        with self._connect() as conn:
            conn.executescript(SCHEMA)
            # A restart mid-task: run it again from the start.
            conn.execute("UPDATE tasks SET state=?, started=NULL WHERE state=?", (WAITING, RUNNING))

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def _changed(self) -> None:
        if self.on_change:
            try:
                self.on_change()
            except Exception:  # noqa: BLE001
                logger.exception("Task queue change callback failed")

    # ------------------------------------------------------------------ adding and managing
    def add_batch(self, name: str, instructions: str, items: list[dict], options: dict | None = None) -> dict:
        items = [i for i in items if (i.get("body") or "").strip()]
        if not items:
            raise ValueError("Add at least one item: paste them separated by --- lines, or attach files.")
        bid = uuid.uuid4().hex[:10]
        name = " ".join((name or "").split())[:60] or time.strftime("Tasks %d %b %H:%M")
        with self._lock, self._connect() as conn:
            conn.execute("INSERT INTO batches VALUES (?, ?, ?, ?, ?)", (bid, name, instructions or "", json.dumps(options or {}), time.time()))
            for position, item in enumerate(items):
                conn.execute(
                    "INSERT INTO tasks (id, batch_id, position, title, body, state) VALUES (?, ?, ?, ?, ?, ?)",
                    (uuid.uuid4().hex[:10], bid, position, item.get("title") or f"Task {position + 1}", item["body"], WAITING),
                )
        self._changed()
        self._wake.set()
        return self.batch(bid)

    def cancel(self, bid: str | None = None) -> int:
        """Cancel waiting tasks (of one batch, or all) and stop the one running."""
        with self._lock, self._connect() as conn:
            where, args = ("AND batch_id=?", (bid,)) if bid else ("", ())
            running = [r["cid"] for r in conn.execute(f"SELECT cid FROM tasks WHERE state=? {where}", (RUNNING, *args))]
            count = conn.execute(f"UPDATE tasks SET state=?, finished=? WHERE state=? {where}", (CANCELLED, time.time(), WAITING, *args)).rowcount
        for cid in running:
            if cid:
                self.turns.cancel(cid)
        self._changed()
        return count + len(running)

    def retry_failed(self, bid: str | None = None) -> int:
        with self._lock, self._connect() as conn:
            where, args = ("AND batch_id=?", (bid,)) if bid else ("", ())
            count = conn.execute(
                f"UPDATE tasks SET state=?, cid=NULL, error=NULL, started=NULL, finished=NULL WHERE state IN (?, ?) {where}",
                (WAITING, FAILED, CANCELLED, *args),
            ).rowcount
        self._changed()
        self._wake.set()
        return count

    # ------------------------------------------------------------------ reading
    def batch(self, bid: str) -> dict | None:
        return next((b for b in self.batches(limit=1000) if b["id"] == bid), None)

    def batches(self, limit: int = 20) -> list[dict]:
        with self._connect() as conn:
            batches = [dict(r) for r in conn.execute("SELECT * FROM batches ORDER BY created DESC LIMIT ?", (limit,))]
            for batch in batches:
                batch["options"] = json.loads(batch["options"])
                batch["tasks"] = [dict(r) for r in conn.execute("SELECT * FROM tasks WHERE batch_id=? ORDER BY position", (batch["id"],))]
        return batches

    def active_chats(self) -> set[str]:
        """Chats of tasks running now, plus a marker while any wait: keeps the PC awake."""
        with self._connect() as conn:
            rows = conn.execute("SELECT id, state, cid FROM tasks WHERE state IN (?, ?)", (WAITING, RUNNING)).fetchall()
        return {r["cid"] or f"task:{r['id']}" for r in rows}

    def summary(self) -> dict:
        with self._connect() as conn:
            counts = dict(conn.execute("SELECT state, COUNT(*) FROM tasks GROUP BY state").fetchall())
        return {state: counts.get(state, 0) for state in (WAITING, RUNNING, DONE, FAILED)}

    # ------------------------------------------------------------------ running
    def _next(self) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT t.*, b.name AS batch_name, b.instructions, b.options FROM tasks t JOIN batches b ON b.id = t.batch_id "
                "WHERE t.state=? ORDER BY b.created, t.position LIMIT 1",
                (WAITING,),
            ).fetchone()
        return dict(row) if row else None

    def _set(self, tid: str, **changes) -> None:
        columns = ", ".join(f"{k}=?" for k in changes)
        with self._lock, self._connect() as conn:
            conn.execute(f"UPDATE tasks SET {columns} WHERE id=?", (*changes.values(), tid))
        self._changed()

    def run_one(self) -> bool:
        """Run the next waiting task to completion. Returns False when there's nothing to do."""
        task = self._next()
        if task is None:
            return False
        options = json.loads(task["options"])
        self._set(task["id"], state=RUNNING, started=time.time())
        try:
            cid, _, turn, _ = self.turns.submit(
                cid=None,
                text=compose(task["instructions"], task["body"]),
                model_key=options.get("model") or None,
                web=bool(options.get("web")),
                kb=bool(options.get("kb")),
                thinking=bool(options.get("thinking")),
                kv=options.get("kv") or None,
                scope=options.get("scope") or "",
            )
            self.turns.store.rename(cid, f"{task['batch_name']} · {task['title']}"[:80])
            self._set(task["id"], cid=cid)
            version = -1
            while not turn.done:
                turn.wait(version, timeout=self.poll)
                version = turn.snapshot()[0]
            history = turn.snapshot()[1]
            last = str((history[-1] or {}).get("content") or "") if history else ""
            if turn.cancel.is_set():
                self._set(task["id"], state=CANCELLED, finished=time.time())
            elif "Something went wrong" in last:
                self._set(task["id"], state=FAILED, error=last[:300], finished=time.time())
            else:
                self._set(task["id"], state=DONE, finished=time.time())
        except Exception as e:  # noqa: BLE001 - one bad task mustn't stop the queue
            logger.exception("Task %s failed", task["id"])
            self._set(task["id"], state=FAILED, error=str(e)[:300], finished=time.time())
        return True

    def start(self) -> None:
        def loop():
            while not self._stop.is_set():
                if not self.run_one():
                    self._wake.wait(5)
                    self._wake.clear()

        threading.Thread(target=loop, name="task-queue", daemon=True).start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
