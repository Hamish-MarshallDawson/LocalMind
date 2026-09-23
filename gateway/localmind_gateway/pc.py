"""Talking to LocalMind on the PC, and noticing when the PC itself is on."""
from __future__ import annotations

import json
import shutil
import subprocess
from typing import AsyncIterator

import httpx

from .settings import Settings

API = "/localmind/api"


class PcError(RuntimeError):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class PcLink:
    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None):
        self.settings = settings
        # LocalMind's HTTPS certificate is self-signed, and the gateway reaches it by IP. The
        # shared token authenticates both ends; on the LAN or tailnet that's what matters.
        self.client = httpx.AsyncClient(
            base_url=settings.pc_url,
            verify=False,
            headers={"Authorization": f"Bearer {settings.token}"},
            timeout=httpx.Timeout(15.0),
            transport=transport,
        )

    async def close(self) -> None:
        await self.client.aclose()

    async def status(self) -> dict | None:
        """LocalMind's status, or None when it isn't answering (PC off, booting, or loading)."""
        try:
            response = await self.client.get(f"{API}/status", timeout=4.0)
        except httpx.HTTPError:
            return None
        if response.status_code != 200:
            return None
        try:
            return response.json()
        except ValueError:
            return None

    async def _json(self, method: str, path: str, **kwargs) -> dict:
        try:
            response = await self.client.request(method, API + path, **kwargs)
        except httpx.HTTPError as e:
            raise PcError(f"Couldn't reach LocalMind: {e}") from e
        try:
            data = response.json()
        except ValueError:
            data = {"error": response.text[:200]}
        if response.status_code >= 400:
            raise PcError(data.get("error") or f"LocalMind answered {response.status_code}", response.status_code)
        return data

    async def start_turn(self, payload: dict) -> dict:
        return await self._json("POST", "/turns", json=payload)

    async def cancel_turn(self, cid: str) -> dict:
        return await self._json("POST", f"/turns/{cid}/cancel")

    async def conversation(self, cid: str) -> dict | None:
        try:
            return await self._json("GET", f"/conversations/{cid}")
        except PcError as e:
            if e.status == 404:
                return None
            raise

    async def delete_conversation(self, cid: str) -> dict:
        return await self._json("DELETE", f"/conversations/{cid}")

    async def download(self, cid: str, name: str) -> bytes:
        try:
            response = await self.client.get(f"{API}/files/{cid}/{name}", timeout=60.0)
        except httpx.HTTPError as e:
            raise PcError(f"Couldn't reach LocalMind: {e}") from e
        if response.status_code != 200:
            raise PcError(f"LocalMind answered {response.status_code}", response.status_code)
        return response.content

    async def decide_request(self, request_id: str, approve: bool) -> dict:
        return await self._json("POST", f"/requests/{request_id}", json={"approve": approve}, timeout=180.0)

    async def power(self, action: str, **extra) -> dict:
        return await self._json("POST", "/power", json={"action": action, **extra})

    async def events(self, cid: str, start: int) -> AsyncIterator[tuple[str, dict]]:
        """The answer as it's written: (event, data) pairs, ending with ("done", ...)."""
        timeout = httpx.Timeout(15.0, read=600.0)  # a long tool call can go quiet for minutes
        try:
            async with self.client.stream("GET", f"{API}/turns/{cid}/events", params={"start": start}, timeout=timeout) as response:
                if response.status_code != 200:
                    raise PcError(f"LocalMind answered {response.status_code}", response.status_code)
                event, data = "message", []
                async for line in response.aiter_lines():
                    if line.startswith("event:"):
                        event = line[6:].strip()
                    elif line.startswith("data:"):
                        data.append(line[5:].strip())
                    elif not line and data:
                        yield event, json.loads("\n".join(data))
                        event, data = "message", []
        except httpx.HTTPError as e:
            raise PcError(f"Lost the connection to LocalMind: {e}") from e


def tailscale_peer_online(name: str) -> bool | None:
    """Whether Tailscale sees the PC online: tells "booting" apart from "still off". None if unknown."""
    if not name or not shutil.which("tailscale"):
        return None
    try:
        result = subprocess.run(["tailscale", "status", "--json"], capture_output=True, text=True, timeout=5)
        peers = json.loads(result.stdout).get("Peer") or {}
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    name = name.lower()
    for peer in peers.values():
        if name in (str(peer.get("HostName", "")).lower(), str(peer.get("DNSName", "")).split(".")[0].lower()):
            return bool(peer.get("Online"))
    return None
