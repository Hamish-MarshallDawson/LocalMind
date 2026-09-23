"""The gateway web app: the page, its API, and the worker that gets messages to the PC.

A message goes through: queued -> waking (Wake-on-LAN sent, waiting for LocalMind) -> sending ->
running (the answer streams back) -> done. The page follows along over one server-sent event
stream, which also carries the PC's status whenever it reports or goes quiet.
"""
from __future__ import annotations

import asyncio
import contextlib
import hmac
import json
import logging
import re
import time
from pathlib import Path
from typing import Callable

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import wol
from .pc import PcError, PcLink, tailscale_peer_online
from .settings import Settings
from .store import ACTIVE, GatewayStore

logger = logging.getLogger("localmind_gateway")

STATIC = Path(__file__).with_name("static")
POLL_WHILE_WAKING = 4.0  # seconds between "is LocalMind up yet?" checks
RESEND_WOL_EVERY = 60.0
MONITOR_EVERY = 15.0
SAVE_REPLY_EVERY = 1.0  # seconds between writes of a streaming reply to disk
SHUTDOWN_SHOWN_FOR = 180.0  # after the PC's "shutting down" report, then it's simply offline
SAFE_PART = re.compile(r"[A-Za-z0-9][A-Za-z0-9 _.()-]{0,120}")


SEPARATOR = re.compile(r"^\s*-{3,}\s*$", re.M)


def split_items(text: str) -> list[dict]:
    """Items pasted into one box, separated by lines of three or more dashes (as on the PC)."""
    items = []
    for block in SEPARATOR.split(text or ""):
        body = block.strip()
        if body:
            first = next(line.strip() for line in body.splitlines() if line.strip())
            items.append({"title": first[:70].rstrip(" :.,"), "body": body})
    return items


def page_version() -> str:
    """A stamp for the current page files, so an open tab can notice it has been updated."""
    import hashlib

    digest = hashlib.sha1()
    for name in sorted(p.name for p in STATIC.iterdir() if p.is_file()):
        file = STATIC / name
        digest.update(name.encode())
        digest.update(str(file.stat().st_mtime_ns).encode())
        digest.update(str(file.stat().st_size).encode())
    return digest.hexdigest()[:12]


def _title(text: str, limit: int = 48) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


class Gateway:
    def __init__(
        self,
        settings: Settings,
        store: GatewayStore,
        link: PcLink,
        *,
        wake: Callable[[], None] | None = None,
        peer_online: Callable[[], bool | None] | None = None,
        clock: Callable[[], float] = time.time,
        poll_interval: float = POLL_WHILE_WAKING,
    ):
        self.settings = settings
        self.store = store
        self.link = link
        self._wake = wake or (lambda: wol.wake(settings.pc_mac, settings.wol_broadcast, settings.wol_port))
        self._peer_online = peer_online or (lambda: tailscale_peer_online(settings.pc_tailscale_name))
        self.clock = clock
        self.poll_interval = poll_interval
        self.subscribers: set[asyncio.Queue] = set()
        self.kick = asyncio.Event()
        self.waking_since: float | None = None
        self.wake_detail: str | None = None
        self.last_contact: float | None = None  # last time LocalMind answered us directly
        self._last_pc_state: str | None = None
        self._tasks: list[asyncio.Task] = []

    # ------------------------------------------------------------------ live updates
    def broadcast(self, kind: str, data) -> None:
        for queue in list(self.subscribers):
            with contextlib.suppress(asyncio.QueueFull):
                queue.put_nowait((kind, data))

    def pc_state(self) -> dict:
        report, received = self.store.last_report()
        now = self.clock()
        age = None if received is None else now - received
        reported = (report or {}).get("state")
        recent_contact = self.last_contact is not None and now - self.last_contact < self.settings.offline_after
        if reported == "shutting_down" and age is not None and age < SHUTDOWN_SHOWN_FOR:
            state = "shutting_down"
        elif (reported == "online" and age is not None and age < self.settings.offline_after) or (recent_contact and reported != "shutting_down"):
            state = "online"
        elif self.waking_since is not None:
            state = "waking"
        else:
            state = "offline"
        return {
            "state": state,
            "report": report,
            "received_at": received,
            "waking_since": self.waking_since,
            "wake_detail": self.wake_detail,
            "can_wake": bool(self.settings.pc_mac),
            "pc_ui_url": self.settings.pc_ui_url or None,
            "now": now,
        }

    def publish_pc(self) -> None:
        state = self.pc_state()
        self._last_pc_state = state["state"]
        self.broadcast("pc", state)

    def publish_job(self, job: dict) -> None:
        self.broadcast("job", job)

    # ------------------------------------------------------------------ reports from the PC
    def receive_report(self, report: dict) -> None:
        self.store.save_report(report)
        if report.get("state") == "online":
            self.last_contact = self.clock()
        elif report.get("state") in ("shutting_down", "stopped"):
            self.last_contact = None
        self.publish_pc()
        if report.get("conversations"):
            self.broadcast("conversations", self.store.list_conversations())
        self.kick.set()  # a queued message can go now

    # ------------------------------------------------------------------ waking
    async def send_wake(self) -> None:
        if not self.settings.pc_mac:
            raise PcError("No MAC address configured (LMG_PC_MAC), so the PC can't be woken.")
        await asyncio.to_thread(self._wake)
        logger.info("Sent Wake-on-LAN to %s", self.settings.pc_mac)

    async def wait_for_pc(self, on_progress: Callable[[str], None], cancelled: Callable[[], bool]) -> dict | None:
        """Wake the PC if LocalMind isn't answering, then wait for it. Returns its status or None."""
        status = await self.link.status()
        if status is not None:
            self.last_contact = self.clock()
            return status
        self.waking_since = self.clock()
        self.wake_detail = "Sending the wake-up signal"
        on_progress(self.wake_detail)
        self.publish_pc()
        try:
            await self.send_wake()
            next_wol = self.clock() + RESEND_WOL_EVERY
            deadline = self.clock() + self.settings.wake_timeout
            while True:
                await asyncio.sleep(self.poll_interval)
                if cancelled():
                    return None
                status = await self.link.status()
                if status is not None:
                    self.last_contact = self.clock()
                    return status
                if self.clock() > deadline:
                    raise PcError(
                        f"The PC didn't come online within {self.settings.wake_timeout / 60:g} minutes. "
                        "Check Wake-on-LAN is enabled in its BIOS, and that LocalMind starts with Windows."
                    )
                peer = await asyncio.to_thread(self._peer_online)
                detail = "PC is on, starting LocalMind" if peer else "Waiting for the PC to start"
                if detail != self.wake_detail:
                    self.wake_detail = detail
                    on_progress(detail)
                    self.publish_pc()
                if self.clock() > next_wol:
                    # Resend even if Tailscale says the PC is on: it lags a minute or two behind a
                    # PC that has just switched off, and a packet to a running PC does nothing.
                    await self.send_wake()
                    next_wol = self.clock() + RESEND_WOL_EVERY
        finally:
            self.waking_since = None
            self.wake_detail = None
            self.publish_pc()

    # ------------------------------------------------------------------ files the PC produced
    def file_path(self, cid: str, name: str) -> Path | None:
        """Where a kept copy of a chat's output file lives (or would), if the names are sane."""
        if not SAFE_PART.fullmatch(cid) or not SAFE_PART.fullmatch(name) or name.startswith("."):
            return None
        return self.settings.data_dir / "files" / cid / name

    async def keep_files(self, conv: dict) -> None:
        """Copy the chat's output files (compiled CVs...) here, so they're there when the PC isn't."""
        for message in conv.get("messages") or []:
            ref = message.get("file")
            if not ref or "/" not in ref:
                continue
            cid, name = ref.split("/", 1)
            target = self.file_path(cid, name)
            if target is None or target.exists():
                continue
            try:
                data = await self.link.download(cid, name)
            except PcError as e:
                logger.warning("Couldn't copy %s from the PC: %s", ref, e)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)

    # ------------------------------------------------------------------ delivering messages
    def _job_update(self, job_id: str, **changes) -> dict:
        job = self.store.update_job(job_id, **changes)
        self.publish_job(job)
        return job

    def _cancelled(self, job_id: str) -> bool:
        job = self.store.get_job(job_id)
        return job is None or job["state"] == "cancelled"

    async def deliver(self, job: dict) -> None:
        job_id, cid = job["id"], job["conversation_id"]
        try:
            status = await self.wait_for_pc(
                lambda detail: self._job_update(job_id, state="waking", detail=detail),
                lambda: self._cancelled(job_id),
            )
            if status is None:
                return  # cancelled while waiting
            self._job_update(job_id, state="sending", detail="Sending your message")
            payload = {**job["options"], "text": job["text"], "conversation_id": cid}
            for attempt in range(20):
                try:
                    started = await self.link.start_turn(payload)
                    break
                except PcError as e:
                    if e.status != 409 or attempt == 19:
                        raise
                    self._job_update(job_id, detail="Waiting for this chat's previous answer")
                    await asyncio.sleep(3)
            self._job_update(job_id, state="running", detail="Thinking")
            await self.follow(job_id, cid, started.get("start", 0))
            conv = await self.link.conversation(cid)
            if conv and cid not in self.store.pending_deletions():  # deleted while it answered
                self.store.upsert_conversation(conv)
                await self.keep_files(conv)
                self.broadcast("conversation", conv)
                self.broadcast("conversations", self.store.list_conversations())
            if not self._cancelled(job_id):
                self._job_update(job_id, state="done", detail=None)
        except PcError as e:
            logger.warning("Message %s failed: %s", job_id, e)
            if not self._cancelled(job_id):
                self._job_update(job_id, state="failed", error=str(e), detail=None)
        except Exception as e:  # noqa: BLE001 - a bug must not stop the queue
            logger.exception("Message %s failed", job_id)
            self._job_update(job_id, state="failed", error=f"Gateway error: {e}", detail=None)

    async def follow(self, job_id: str, cid: str, start: int) -> None:
        last_save = 0.0
        async for kind, data in self.link.events(cid, start):
            messages, status, context = data.get("messages") or [], data.get("status"), data.get("context")
            job = {**self.store.get_job(job_id), "reply": messages, "detail": status, "context": context}
            if context:
                self.store.set_context(cid, context)
            if kind == "done" or self.clock() - last_save > SAVE_REPLY_EVERY:
                job = {**self.store.update_job(job_id, reply=messages, detail=status), "context": context}
                last_save = self.clock()
            self.publish_job(job)
            if kind == "done":
                return

    async def deliver_deletions(self) -> None:
        """Chats deleted here while the PC was off: delete them there too, now it's on."""
        for cid in self.store.pending_deletions():
            try:
                await self.link.delete_conversation(cid)
            except PcError as e:
                if e.status is None:
                    return  # PC unreachable: try again later
                logger.warning("Couldn't delete chat %s on the PC: %s", cid, e)
            self.store.deletion_done(cid)

    async def worker(self) -> None:
        while True:
            if self.store.pending_deletions() and self.pc_state()["state"] == "online":
                await self.deliver_deletions()
            job = self.store.next_queued()
            if job is None:
                self.kick.clear()
                with contextlib.suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(self.kick.wait(), timeout=10)
                continue
            await self.deliver(job)

    async def monitor(self) -> None:
        """Notice the PC going quiet (it can't tell us when the power is cut)."""
        while True:
            await asyncio.sleep(MONITOR_EVERY)
            state = self.pc_state()["state"]
            if state != self._last_pc_state:
                self.publish_pc()

    def start(self) -> None:
        self._tasks = [asyncio.create_task(self.worker()), asyncio.create_task(self.monitor())]

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        await self.link.close()


# ---------------------------------------------------------------------------- web app

def create_app(settings: Settings | None = None, *, gateway: Gateway | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    for problem in settings.problems():
        logger.warning(problem)
    if gateway is None:
        store = GatewayStore(settings.data_dir / "gateway.db")
        gateway = Gateway(settings, store, PcLink(settings))
    store = gateway.store

    @contextlib.asynccontextmanager
    async def lifespan(app):
        gateway.start()
        yield
        await gateway.stop()

    app = FastAPI(title="LocalMind gateway", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.gateway = gateway

    def user_of(request: Request) -> str | None:
        """Who's asking, from the identity headers `tailscale serve` adds to tailnet requests."""
        login = request.headers.get("tailscale-user-login", "").strip().lower()
        if settings.allowed_users:
            return login if login in settings.allowed_users else None
        return login or "local"

    def pc_authorised(request: Request) -> bool:
        given = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
        return bool(settings.token) and hmac.compare_digest(given.encode(), settings.token.encode())

    @app.middleware("http")
    async def require_user(request: Request, call_next):
        path = request.url.path
        if path == "/api/pc/report" or path in ("/manifest.webmanifest", "/icon.svg", "/sw.js"):
            return await call_next(request)
        if user_of(request) is None:
            who = request.headers.get("tailscale-user-login") or "an unknown user (open this through Tailscale)"
            if path.startswith("/api/"):
                return JSONResponse({"error": f"Not allowed: {who}"}, status_code=403)
            return JSONResponse({"error": f"This LocalMind gateway isn't shared with {who}."}, status_code=403)
        return await call_next(request)

    # -------------------------------------------------------------- the page's API
    version = page_version()

    @app.get("/api/state")
    async def state(request: Request):
        return {
            "version": version,
            "user": user_of(request),
            "pc": gateway.pc_state(),
            "conversations": store.list_conversations(),
            "jobs": store.jobs(active_only=True),
        }

    @app.get("/api/conversations/{cid}")
    async def conversation(cid: str):
        conv = store.get_conversation(cid)
        return conv or JSONResponse({"error": "No such chat"}, status_code=404)

    @app.post("/api/messages")
    async def send_message(request: Request):
        body = await request.json()
        text = str(body.get("text") or "").strip()
        if not text:
            return JSONResponse({"error": "The message is empty"}, status_code=400)
        options = {k: body.get(k) for k in ("model", "kv_cache", "web", "kb", "thinking", "scope") if body.get(k) not in (None, "")}
        cid = body.get("conversation_id") or None
        existing = store.get_conversation(cid) if cid else None
        job = store.create_job(cid, text, options, existing["title"] if existing else _title(text))
        gateway.publish_job(job)
        gateway.broadcast("conversations", store.list_conversations())
        gateway.kick.set()
        return job

    @app.get("/api/files/{cid}/{name}")
    async def output_file(cid: str, name: str):
        path = gateway.file_path(cid, name)
        if path is None:
            return JSONResponse({"error": "Bad file name"}, status_code=400)
        if not path.exists() and gateway.pc_state()["state"] == "online":
            await gateway.keep_files({"messages": [{"file": f"{cid}/{name}"}]})
        if not path.exists():
            return JSONResponse({"error": "That file isn't here yet; it's copied when the PC is on."}, status_code=404)
        return FileResponse(path, filename=name)

    @app.delete("/api/conversations/{cid}")
    async def delete_conversation(cid: str):
        running = [j for j in store.jobs(active_only=True) if j["conversation_id"] == cid and j["state"] == "running"]
        for job in running:
            with contextlib.suppress(PcError):
                await gateway.link.cancel_turn(cid)
        store.delete_conversation(cid)
        gateway.broadcast("conversations", store.list_conversations())
        gateway.broadcast("deleted", {"id": cid})
        gateway.kick.set()  # passes the deletion on straight away if the PC is on
        return {"ok": True}

    @app.post("/api/batches")
    async def queue_batch(request: Request):
        """Several tasks at once: each item becomes its own new chat, delivered one after another."""
        body = await request.json()
        instructions = str(body.get("instructions") or "").strip()
        items = split_items(str(body.get("items") or ""))
        if not items:
            return JSONResponse({"error": "Add at least one item, separated by lines of ---"}, status_code=400)
        if len(items) > 50:
            return JSONResponse({"error": "That's more than 50 tasks; split it up."}, status_code=400)
        name = " ".join(str(body.get("name") or "").split())[:40] or "Tasks"
        options = {k: body.get(k) for k in ("model", "kv_cache", "web", "kb", "thinking", "scope") if body.get(k) not in (None, "")}
        jobs = []
        for item in items:
            text = f"{instructions}\n\n---\n\n{item['body']}" if instructions else item["body"]
            job = store.create_job(None, text, options, f"{name} · {item['title']}"[:80])
            gateway.publish_job(job)
            jobs.append(job)
        gateway.broadcast("conversations", store.list_conversations())
        gateway.kick.set()
        return {"queued": len(jobs), "jobs": jobs}

    @app.post("/api/pc/requests/{request_id}")
    async def decide_request(request_id: str, request: Request):
        body = await request.json()
        try:
            result = await gateway.link.decide_request(request_id, bool(body.get("approve")))
        except PcError as e:
            return JSONResponse({"error": str(e)}, status_code=502)
        # The PC reports again straight after any decision, which clears it from the page.
        return result

    @app.post("/api/jobs/{job_id}/cancel")
    async def cancel_job(job_id: str):
        job = store.get_job(job_id)
        if job is None:
            return JSONResponse({"error": "No such message"}, status_code=404)
        if job["state"] == "running":
            with contextlib.suppress(PcError):
                await gateway.link.cancel_turn(job["conversation_id"])
            return job  # it finishes as "stopped" through the normal stream
        if job["state"] in ACTIVE or job["state"] == "failed":
            job = gateway._job_update(job_id, state="cancelled", detail=None)
        return job

    @app.post("/api/jobs/{job_id}/retry")
    async def retry_job(job_id: str):
        job = store.get_job(job_id)
        if job is None or job["state"] not in ("failed", "cancelled"):
            return JSONResponse({"error": "Only failed or cancelled messages can be retried"}, status_code=400)
        job = gateway._job_update(job_id, state="queued", error=None, detail=None, reply=[])
        gateway.kick.set()
        return job

    @app.post("/api/pc/wake")
    async def wake():
        if gateway.pc_state()["state"] == "online":
            return {"ok": True, "detail": "The PC is already on"}

        if not settings.pc_mac:
            return JSONResponse({"error": "No MAC address configured (LMG_PC_MAC), so the PC can't be woken."}, status_code=400)

        async def wake_and_wait():
            with contextlib.suppress(PcError):
                await gateway.wait_for_pc(lambda detail: None, lambda: False)

        if gateway.waking_since is None:
            asyncio.create_task(wake_and_wait())
        return {"ok": True}

    @app.post("/api/pc/power")
    async def power(request: Request):
        body = await request.json()
        action = body.get("action")
        if action not in ("keep_awake", "keepalive", "shutdown", "cancel_shutdown"):
            return JSONResponse({"error": "Unknown action"}, status_code=400)
        try:
            result = await gateway.link.power(action, **{k: v for k, v in body.items() if k != "action"})
        except PcError as e:
            return JSONResponse({"error": str(e)}, status_code=502)
        gateway.last_contact = gateway.clock()
        return result

    @app.get("/api/events")
    async def events(request: Request):
        queue: asyncio.Queue = asyncio.Queue(maxsize=500)
        gateway.subscribers.add(queue)

        async def stream():
            try:
                yield _sse("pc", gateway.pc_state())
                while True:
                    try:
                        kind, data = await asyncio.wait_for(queue.get(), timeout=20)
                        yield _sse(kind, data)
                    except asyncio.TimeoutError:
                        yield ": keep-alive\n\n"  # stops proxies closing an idle stream
                    if await request.is_disconnected():
                        return
            finally:
                gateway.subscribers.discard(queue)

        return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})

    # -------------------------------------------------------------- from the PC
    @app.post("/api/pc/report")
    async def report(request: Request):
        if not pc_authorised(request):
            return JSONResponse({"error": "Bad or missing gateway token"}, status_code=401)
        gateway.receive_report(await request.json())
        return {"ok": True}

    # -------------------------------------------------------------- the page
    @app.get("/")
    async def index():
        return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})

    @app.get("/sw.js")
    async def service_worker():
        return FileResponse(STATIC / "sw.js", media_type="text/javascript", headers={"Cache-Control": "no-cache"})

    app.mount("/", StaticFiles(directory=STATIC), name="static")
    return app


def _sse(kind: str, data) -> str:
    return f"event: {kind}\ndata: {json.dumps(data, default=str)}\n\n"
