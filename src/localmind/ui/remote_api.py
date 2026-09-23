"""The API the always-on gateway uses to talk to LocalMind: start an answer, follow it, read a
chat, and keep the PC awake or shut it down.

Protected by a shared secret (LOCALMIND_GATEWAY_TOKEN) rather than the web UI's login, since the
caller is a program. Without the variable set, every route answers 404: the API doesn't exist.
"""
from __future__ import annotations

import asyncio
import hmac
import json
import logging
import re
from typing import Callable

from fastapi import Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.routing import APIRoute

from localmind.remote import context_summary, export_conversation, export_messages, gateway_token

from .turns import TurnBusy, TurnManager

logger = logging.getLogger(__name__)

PREFIX = "/localmind/api"
POLL = 0.2  # seconds between checks for new tokens while streaming
CHAT_ID = re.compile(r"[A-Za-z0-9_-]{6,32}")


def remote_routes(turns: TurnManager, store, power, snapshot: Callable[[], dict], token: str | None = None, extensions=None) -> list[APIRoute]:
    secret = gateway_token() if token is None else token

    def refused(request: Request) -> JSONResponse | None:
        if not secret:
            return JSONResponse({"error": "Not found"}, status_code=404)
        given = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
        if not hmac.compare_digest(given.encode(), secret.encode()):
            return JSONResponse({"error": "Bad or missing gateway token"}, status_code=401)
        return None

    async def status(request: Request):
        if denied := refused(request):
            return denied
        return snapshot()

    async def start_turn(request: Request):
        if denied := refused(request):
            return denied
        try:
            body = await request.json()
        except ValueError:
            return JSONResponse({"error": "Expected JSON"}, status_code=400)
        text = str(body.get("text") or "").strip()
        if not text:
            return JSONResponse({"error": "The message is empty"}, status_code=400)
        cid = str(body.get("conversation_id") or "")
        if cid and not CHAT_ID.fullmatch(cid):
            return JSONResponse({"error": "Chat ids are 6-32 letters, digits, - or _"}, status_code=400)
        power.touch("message from the gateway")
        try:
            cid, history, turn, title = turns.submit(
                cid=cid or None,
                text=text,
                model_key=body.get("model") or None,
                web=bool(body.get("web")),
                kb=bool(body.get("kb")),
                thinking=bool(body.get("thinking")),
                kv=body.get("kv_cache") or None,
                voice=bool(body.get("voice")),
                scope=str(body.get("scope") or ""),
            )
        except TurnBusy as e:
            return JSONResponse({"error": str(e)}, status_code=409)
        return {"conversation_id": cid, "title": title, "start": len(history)}

    async def turn_events(request: Request):
        """Server-sent events: the reply so far each time it changes, then a final `done`."""
        if denied := refused(request):
            return denied
        cid = request.path_params["cid"]
        start = int(request.query_params.get("start", "0") or 0)
        turn = turns.get(cid)

        async def stream():
            if turn is None:
                conv = export_conversation(store, cid)
                yield _event("done", {"messages": (conv or {}).get("messages", [])[start:], "status": None})
                return
            version = -1
            while True:
                snap_version, history, status_text, context, done = turn.snapshot()
                if snap_version != version or done:
                    version = snap_version
                    kind = "done" if done else "progress"
                    yield _event(kind, {"messages": export_messages(history[start:]), "status": status_text, "context": context_summary(context)})
                    if done:
                        return
                if await request.is_disconnected():
                    return  # the turn carries on; the gateway can pick it up again
                await asyncio.sleep(POLL)

        return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-store"})

    async def cancel_turn(request: Request):
        if denied := refused(request):
            return denied
        power.touch("stopped an answer from the gateway")
        return {"cancelled": turns.cancel(request.path_params["cid"])}

    async def conversation(request: Request):
        if denied := refused(request):
            return denied
        conv = export_conversation(store, request.path_params["cid"])
        return conv or JSONResponse({"error": "No such chat"}, status_code=404)

    async def delete_conversation(request: Request):
        if denied := refused(request):
            return denied
        cid = request.path_params["cid"]
        power.touch("deleted a chat from the gateway")
        turns.cancel(cid)  # an answer still running would otherwise save the chat back
        existed = store.get(cid) is not None
        if existed:
            store.delete(cid)
        return {"deleted": existed}

    async def output_file(request: Request):
        """A file a tool produced in a chat (a compiled CV, say), for the gateway to keep a copy."""
        if denied := refused(request):
            return denied
        from localmind.tools.documents import _safe_name, outputs_dir

        cid = request.path_params["cid"]
        try:
            name = _safe_name(request.path_params["name"])
        except ValueError:
            return JSONResponse({"error": "Bad file name"}, status_code=400)
        if not CHAT_ID.fullmatch(cid):
            return JSONResponse({"error": "Bad chat id"}, status_code=400)
        path = outputs_dir(turns.config, cid) / name
        if not path.is_file():
            return JSONResponse({"error": "No such file"}, status_code=404)
        return FileResponse(path, filename=name)

    async def decide_request(request: Request):
        """Approve or deny the model's request for a skill or MCP server, from the phone."""
        if denied := refused(request):
            return denied
        if extensions is None:
            return JSONResponse({"error": "Extensions aren't enabled"}, status_code=404)
        try:
            body = await request.json()
        except ValueError:
            body = {}
        power.touch("answered a tool request from the gateway")
        from fastapi.concurrency import run_in_threadpool

        try:
            return await run_in_threadpool(extensions.requests.decide, request.path_params["rid"], bool(body.get("approve")))
        except KeyError:
            return JSONResponse({"error": "No such request"}, status_code=404)

    async def power_action(request: Request):
        if denied := refused(request):
            return denied
        try:
            body = await request.json()
        except ValueError:
            body = {}
        action = body.get("action")
        if action == "keepalive":
            power.touch("activity from the gateway")
        elif action == "keep_awake":
            power.keep_awake(float(body.get("minutes") or 60))
        elif action == "shutdown":
            power.shutdown(str(body.get("reason") or "Shut down from the gateway"), grace=int(body.get("grace") or 30))
        elif action == "cancel_shutdown":
            power.cancel_shutdown("cancelled from the gateway")
        else:
            return JSONResponse({"error": f"Unknown action {action!r}"}, status_code=400)
        return power.status()

    return [
        APIRoute(f"{PREFIX}/status", status, methods=["GET"]),
        APIRoute(f"{PREFIX}/turns", start_turn, methods=["POST"]),
        APIRoute(PREFIX + "/turns/{cid}/events", turn_events, methods=["GET"]),
        APIRoute(PREFIX + "/turns/{cid}/cancel", cancel_turn, methods=["POST"]),
        APIRoute(PREFIX + "/conversations/{cid}", conversation, methods=["GET"]),
        APIRoute(PREFIX + "/conversations/{cid}", delete_conversation, methods=["DELETE"]),
        APIRoute(f"{PREFIX}/power", power_action, methods=["POST"]),
        APIRoute(PREFIX + "/files/{cid}/{name}", output_file, methods=["GET"]),
        APIRoute(PREFIX + "/requests/{rid}", decide_request, methods=["POST"]),
    ]


def _event(kind: str, data: dict) -> str:
    return f"event: {kind}\ndata: {json.dumps(data, default=str)}\n\n"
