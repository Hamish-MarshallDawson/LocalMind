"""MCP servers: other programs' tools, made available to the model.

A server is either a command LocalMind starts (stdio, e.g. `npx -y @modelcontextprotocol/server-...`)
or a URL it connects to (streamable HTTP). Each keeps one connection open on a background event
loop; its tools join the tool registry as `mcp__<server>__<tool>`, so the model calls them like
any other tool. The list of servers lives in a JSON file beside the rest of LocalMind's data.

Adding a server runs a program on this PC, so servers are only ever added by you (or approved by
you after the model asks): never by the model on its own.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import shlex
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
CALL_TIMEOUT = 120.0
CONNECT_TIMEOUT = 60.0


class McpError(ValueError):
    pass


def tool_name(server: str, tool: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_]", "_", tool)
    return f"mcp__{server.replace('-', '_')}__{safe}"[:64]


class McpHub:
    def __init__(self, path: str | Path, registry):
        self.path = Path(path)
        self.registry = registry
        self.servers: dict[str, dict] = self._load()
        self.status: dict[str, dict] = {}
        self._clients: dict[str, object] = {}
        self._stops: dict[str, asyncio.Event] = {}
        self._tool_names: dict[str, list[str]] = {}
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, name="mcp", daemon=True)
        self._thread.start()

    # ------------------------------------------------------------------ the saved list
    def _load(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.servers, indent=2), encoding="utf-8")

    @staticmethod
    def spec_from(target: str, env: dict | None = None) -> dict:
        """A server spec from what you typed: a URL, or a command line."""
        target = target.strip()
        if re.match(r"^https?://", target):
            return {"url": target}
        parts = shlex.split(target, posix=False)
        if not parts:
            raise McpError("Give a command (e.g. npx -y @modelcontextprotocol/server-filesystem C:/notes) or a URL.")
        return {"command": parts[0].strip('"'), "args": [p.strip('"') for p in parts[1:]], "env": env or {}}

    # ------------------------------------------------------------------ connecting
    def start(self) -> None:
        for name in self.servers:
            self._submit(self._serve(name))

    def add(self, name: str, spec: dict, wait: float = CONNECT_TIMEOUT) -> dict:
        name = name.strip().lower()
        if not NAME.match(name):
            raise McpError("Server names are lower-case letters, digits, - and _ (up to 32).")
        if name in self.servers:
            raise McpError(f"There's already a server called {name}.")
        if not (spec.get("url") or spec.get("command")):
            raise McpError("A server needs a command or a URL.")
        self.servers[name] = spec
        self._save()
        self._submit(self._serve(name))
        self._wait_connected(name, wait)
        return self.status.get(name, {})

    def remove(self, name: str) -> bool:
        if name not in self.servers:
            return False
        del self.servers[name]
        self._save()
        stop = self._stops.get(name)
        if stop is not None:
            self._loop.call_soon_threadsafe(stop.set)
        self._unregister(name)
        self.status.pop(name, None)
        return True

    def _wait_connected(self, name: str, timeout: float) -> None:
        import time

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            state = self.status.get(name, {}).get("state")
            if state in ("connected", "failed"):
                return
            time.sleep(0.1)

    def _submit(self, coro, wait: float | None = None):
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result(wait) if wait else future

    async def _serve(self, name: str) -> None:
        """Hold the server's connection open until it's removed; register its tools meanwhile."""
        from mcp import Client, StdioServerParameters

        spec = self.servers[name]
        self.status[name] = {"state": "connecting", "tools": [], "error": None}
        stop = asyncio.Event()
        self._stops[name] = stop
        try:
            if spec.get("url"):
                target = spec["url"]
            else:
                target = StdioServerParameters(command=spec["command"], args=list(spec.get("args") or []), env=spec.get("env") or None)
            async with Client(target, read_timeout_seconds=CALL_TIMEOUT) as client:
                listed = await asyncio.wait_for(client.list_tools(), CONNECT_TIMEOUT)
                self._clients[name] = client
                self._register(name, listed.tools)
                self.status[name] = {"state": "connected", "tools": [t.name for t in listed.tools], "error": None}
                logger.info("MCP server %s connected with %d tools", name, len(listed.tools))
                await stop.wait()
        except Exception as e:  # noqa: BLE001 - a broken server must not take LocalMind down
            logger.warning("MCP server %s failed: %s", name, e)
            self.status[name] = {"state": "failed", "tools": [], "error": str(e)[:300]}
        finally:
            self._clients.pop(name, None)
            self._unregister(name)

    # ------------------------------------------------------------------ tools
    def _register(self, server: str, tools) -> None:
        names = []
        for tool in tools:
            schema = tool.input_schema or {}
            full = tool_name(server, tool.name)
            self.registry.register(
                name=full,
                description=f"[{server}] {(tool.description or tool.name).strip()}"[:1024],
                parameters=schema.get("properties") or {},
                function=self._caller(server, tool.name),
                required_params=list(schema.get("required") or []),
            )
            names.append(full)
        self._tool_names[server] = names

    def _unregister(self, server: str) -> None:
        for name in self._tool_names.pop(server, []):
            self.registry.unregister(name)

    def _caller(self, server: str, tool: str):
        def call(**arguments) -> str:
            client = self._clients.get(server)
            if client is None:
                return json.dumps({"error": f"The {server} MCP server isn't connected."})
            try:
                result = self._submit(client.call_tool(tool, arguments), wait=CALL_TIMEOUT)
            except Exception as e:  # noqa: BLE001
                return json.dumps({"error": f"{server}.{tool} failed: {e}"})
            texts = [getattr(part, "text", None) or f"[{getattr(part, 'type', 'content')}]" for part in result.content or []]
            payload = {"result": "\n".join(texts)}
            if result.structured_content is not None:
                payload["structured"] = result.structured_content
            if result.is_error:
                payload = {"error": payload["result"] or "The tool reported an error."}
            return json.dumps(payload, default=str)[:50_000]

        return call

    def describe(self) -> list[dict]:
        out = []
        for name, spec in self.servers.items():
            target = spec.get("url") or " ".join([spec.get("command", "")] + list(spec.get("args") or []))
            out.append({"name": name, "target": target, **self.status.get(name, {"state": "stopped", "tools": [], "error": None})})
        return out

    def close(self) -> None:
        for stop in self._stops.values():
            self._loop.call_soon_threadsafe(stop.set)
