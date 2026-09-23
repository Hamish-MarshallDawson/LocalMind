"""LocalMind's side of the always-on gateway.

The gateway (a small always-on machine) is what you open on your phone. It can't see this PC while it's
switched off, so LocalMind keeps it informed: a status report every minute and after every answer,
copies of recent chats for reading offline, and a last report just before an idle shutdown, so
the gateway can tell you when and why the PC went down.
"""
from __future__ import annotations

import logging
import os
import platform
import socket
import threading
import time
from pathlib import Path
from typing import Callable

import httpx

from localmind.config import GatewayConfig

logger = logging.getLogger(__name__)

TOKEN_ENV = "LOCALMIND_GATEWAY_TOKEN"
URL_ENV = "LOCALMIND_GATEWAY_URL"
MAX_MESSAGE_CHARS = 20_000  # per message, in copies sent to the gateway


def gateway_token() -> str:
    return os.environ.get(TOKEN_ENV, "").strip()


def export_message(message: dict) -> dict | None:
    """A chat message as the gateway stores it: plain fields, no Gradio or file-path specifics."""
    if not isinstance(message, dict):
        return None
    role = message.get("role", "assistant")
    content = message.get("content")
    meta = message.get("metadata") or {}
    title = meta.get("title")
    if isinstance(content, dict) or (isinstance(content, (list, tuple)) and content):
        path = content.get("path") if isinstance(content, dict) else content[0]
        out = {"role": role, "kind": "attachment", "text": Path(str(path or "file")).name}
        parts = Path(str(path or "")).parts
        if len(parts) >= 3 and parts[-3] == "outputs":
            out["file"] = f"{parts[-2]}/{parts[-1]}"  # a file a tool made; the gateway can fetch it
        return out
    text = str(content or "")[:MAX_MESSAGE_CHARS]
    if title:
        kind = "thinking" if title.startswith("\U0001F4AD") else "note" if title.startswith("ℹ") else "tool"
        out = {"role": role, "kind": kind, "title": title, "text": text}
        if meta.get("duration") is not None:
            out["duration"] = meta["duration"]
        if meta.get("status") == "pending":
            out["pending"] = True
        return out
    return {"role": role, "kind": "text", "text": text}


def export_messages(history: list[dict]) -> list[dict]:
    return [m for m in (export_message(item) for item in history or []) if m is not None]


def export_conversation(store, cid: str) -> dict | None:
    conv = store.get(cid)
    if conv is None:
        return None
    history, _ = store.load(cid)
    settings = store.get_settings(cid)
    return {
        "id": conv.id,
        "title": conv.title,
        "created_at": conv.created_at,
        "updated_at": conv.updated_at,
        "settings": {k: settings.get(k) for k in ("model", "thinking", "web", "kb", "kv", "scope") if k in settings},
        "context": context_summary(settings.get("context")),
        "messages": export_messages(history),
    }


def context_summary(context: dict | None) -> dict | None:
    """How full the chat's context window is, as the gateway shows it."""
    if not context or not context.get("window"):
        return None
    return {"tokens": int(context.get("tokens") or 0), "window": int(context["window"]), "exact": bool(context.get("exact"))}


def host_info() -> dict:
    return {"host": socket.gethostname(), "os": f"{platform.system()} {platform.release()}"}


class GatewayReporter:
    """Posts status (and changed chats) to the gateway on a timer, after answers, and at shutdown."""

    def __init__(
        self,
        config: GatewayConfig,
        snapshot: Callable[[], dict],
        store,
        *,
        token: str | None = None,
        post: Callable[..., httpx.Response] | None = None,
    ):
        self.config = config
        # Where your gateway lives is yours, not the project's: keep it out of config.yaml.
        self.url = (os.environ.get(URL_ENV) or config.url or "").rstrip("/")
        self.snapshot = snapshot
        self.store = store
        self.token = gateway_token() if token is None else token
        self._post = post or self._http_post
        self._synced_until = 0.0  # chats updated after this still need sending
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self.last_error: str | None = None

    @property
    def configured(self) -> bool:
        return bool(self.url and self.token)

    def _http_post(self, url: str, **kwargs) -> httpx.Response:
        # The gateway sits behind `tailscale serve`; tailnet traffic is already encrypted.
        return httpx.post(url, timeout=15, **kwargs)

    def _changed_chats(self) -> tuple[list[dict], float]:
        chats = [c for c in self.store.list() if c.updated_at > self._synced_until][: self.config.history_chats]
        newest = max((c.updated_at for c in chats), default=self._synced_until)
        exported = [e for e in (export_conversation(self.store, c.id) for c in chats) if e]
        return exported, newest

    def report(self, state: str | None = None, reason: str | None = None) -> bool:
        """Send one report now; `state` overrides the snapshot's own. Returns whether it arrived."""
        if not self.configured:
            return False
        with self._lock:
            try:
                chats, newest = self._changed_chats()
                payload = {"state": "online", **self.snapshot(), "reason": reason, "reported_at": time.time(), "conversations": chats}
                if state:
                    payload["state"] = state
                # Every report while shutting down carries the reason, so a routine one sent after
                # the final report can't overwrite why the PC went off.
                payload["reason"] = reason or (payload.get("power") or {}).get("shutdown_reason")
                known = {c.id for c in self.store.list()}
                payload["conversation_ids"] = sorted(known)  # lets the gateway drop chats deleted here
                response = self._post(
                    self.url + "/api/pc/report",
                    json=payload,
                    headers={"Authorization": f"Bearer {self.token}"},
                )
                if response.status_code >= 400:
                    raise RuntimeError(f"gateway answered {response.status_code}: {response.text[:200]}")
            except Exception as e:  # noqa: BLE001 - the gateway being down must never affect LocalMind
                if self.last_error != str(e):
                    logger.warning("Couldn't report to the gateway at %s: %s", self.url, e)
                self.last_error = str(e)
                return False
            if self.last_error:
                logger.info("Reporting to the gateway again")
            self.last_error = None
            self._synced_until = newest
            return True

    def notify(self) -> None:
        """Something changed (an answer finished): report soon rather than on the next tick."""
        self._wake.set()

    def start(self) -> None:
        if not self.configured:
            if self.url:
                logger.warning("gateway.url is set but %s isn't, so LocalMind won't report to the gateway", TOKEN_ENV)
            return
        logger.info("Reporting status to the gateway at %s", self.url)

        def loop():
            while not self._stop.is_set():
                self.report()
                self._wake.wait(self.config.report_interval_seconds)
                self._wake.clear()
                time.sleep(0.5)  # coalesce a burst of notifications

        threading.Thread(target=loop, name="gateway-report", daemon=True).start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
