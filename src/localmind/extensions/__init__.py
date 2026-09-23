"""Abilities added after installation: skills (instructions), MCP servers (other programs' tools),
and the model's requests for more of either, which wait for your approval."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Callable

from .mcp_hub import McpError, McpHub
from .requests import ToolRequests, register_request_tool
from .skills import SkillError, SkillLibrary, register_skill_tools

__all__ = ["Extensions", "McpError", "McpHub", "SkillError", "SkillLibrary", "ToolRequests"]


class Extensions:
    def __init__(self, data_dir: str | Path, registry, agent=None, on_change: Callable[[], None] | None = None):
        from localmind.tools.documents import current_chat

        root = Path(data_dir)
        self.skills = SkillLibrary(root / "skills")
        self.mcp = McpHub(root / "mcp_servers.json", registry)
        self.requests = ToolRequests(root / "tool_requests.json", install=self._install, on_change=on_change)
        register_skill_tools(registry, self.skills)
        register_request_tool(registry, self.requests, current_chat)
        if agent is not None:
            agent.prompt_extensions.append(self.skills.prompt_block)

    def _install(self, request: dict) -> str:
        if request["kind"] == "skill":
            skill = self.skills.install(request["source"])
            return f"Installed skill {skill.name}."
        spec = McpHub.spec_from(request["source"])
        name = (request.get("name") or "").strip().lower()
        if not name:
            base = spec.get("url") or Path(spec["command"]).stem + "-" + "-".join(spec.get("args") or [])[-20:]
            name = re.sub(r"[^a-z0-9_-]+", "-", base.lower()).strip("-")[:32] or "server"
        status = self.mcp.add(name, spec)
        if status.get("state") != "connected":
            raise McpError(status.get("error") or "the server didn't connect")
        return f"Connected MCP server {name} with {len(status.get('tools') or [])} tools."

    def install_bundled(self) -> list[str]:
        """Skills that ship with LocalMind, added on first run (yours are never overwritten)."""
        added = []
        for folder in sorted((Path(__file__).parent / "bundled").iterdir()):
            if (folder / "SKILL.md").exists() and not (self.skills.directory / folder.name).exists():
                self.skills.install(str(folder))
                added.append(folder.name)
        return added

    def start(self) -> None:
        self.install_bundled()
        self.mcp.start()

    def snapshot(self) -> dict:
        return {
            "skills": [s.as_dict() for s in self.skills.list()],
            "mcp": self.mcp.describe(),
            "requests": self.requests.pending(),
        }
