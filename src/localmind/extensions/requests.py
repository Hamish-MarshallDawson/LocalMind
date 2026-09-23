"""Requests from the model for new abilities, waiting for your yes or no.

The model can't install anything itself: a skill is instructions it would follow, and an MCP server
is a program that would run on this PC, so either could be turned against you by a web page it
read. Instead it calls `request_tool` with what it wants and why; the request shows up in
LocalMind and on the gateway, and only your approval installs it.
"""
from __future__ import annotations

import json
import threading
import time
import uuid
from pathlib import Path
from typing import Callable

KINDS = ("skill", "mcp")


class ToolRequests:
    def __init__(self, path: str | Path, install: Callable[[dict], str], on_change: Callable[[], None] | None = None):
        self.path = Path(path)
        self.install = install  # does the work for an approved request; returns what happened
        self.on_change = on_change
        self._lock = threading.Lock()
        try:
            self._items: list[dict] = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self._items = []

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._items, indent=2), encoding="utf-8")

    def _changed(self) -> None:
        if self.on_change:
            try:
                self.on_change()
            except Exception:  # noqa: BLE001
                pass

    def add(self, kind: str, source: str, reason: str, name: str = "", chat: str = "") -> dict:
        if kind not in KINDS:
            raise ValueError(f"kind must be one of {KINDS}")
        source = source.strip()
        with self._lock:
            for item in self._items:  # asking twice for the same thing is one request
                if item["state"] == "pending" and item["kind"] == kind and item["source"] == source:
                    return item
            item = {
                "id": uuid.uuid4().hex[:10], "kind": kind, "source": source, "name": name.strip(),
                "reason": reason.strip()[:500], "chat": chat, "created": time.time(), "state": "pending", "result": None,
            }
            self._items.append(item)
            self._items = self._items[-100:]
            self._save()
        self._changed()
        return item

    def pending(self) -> list[dict]:
        with self._lock:
            return [dict(i) for i in self._items if i["state"] == "pending"]

    def recent(self, limit: int = 20) -> list[dict]:
        with self._lock:
            return [dict(i) for i in self._items[-limit:]][::-1]

    def decide(self, request_id: str, approve: bool) -> dict:
        with self._lock:
            item = next((i for i in self._items if i["id"] == request_id), None)
            if item is None:
                raise KeyError(request_id)
            if item["state"] != "pending":
                return dict(item)
            item["state"] = "installing" if approve else "denied"
            self._save()
        if approve:
            try:
                result, state = self.install(item), "installed"
            except Exception as e:  # noqa: BLE001 - reported back rather than raised
                result, state = f"Install failed: {e}", "failed"
            with self._lock:
                item["state"], item["result"] = state, result
                self._save()
        self._changed()
        return dict(item)


def register_request_tool(registry, requests: ToolRequests, current_chat) -> None:
    def request_tool(kind: str, source: str, reason: str, name: str = "") -> str:
        try:
            item = requests.add(kind, source, reason, name=name, chat=current_chat.get())
        except ValueError as e:
            return json.dumps({"error": str(e)})
        return json.dumps({
            "request": item["id"],
            "status": "waiting for the user's approval",
            "note": "Nothing is installed until the user approves it in LocalMind. Carry on without it, and "
                    "tell the user what you asked for and why.",
        })

    registry.register(
        name="request_tool",
        description=(
            "Ask the user to install a new ability: a skill (kind 'skill', source: a GitHub link to a folder "
            "with SKILL.md) or an MCP server (kind 'mcp', source: the command to run or its URL). Only the "
            "user can approve it; use this when a task clearly needs something you don't have."
        ),
        parameters={
            "kind": {"type": "string", "description": "'skill' or 'mcp'"},
            "source": {"type": "string", "description": "GitHub link for a skill; command line or URL for an MCP server"},
            "reason": {"type": "string", "description": "What it's for, in one or two sentences, for the user"},
            "name": {"type": "string", "description": "A short name for an MCP server (letters, digits, -)"},
        },
        function=request_tool,
        required_params=["kind", "source", "reason"],
    )
