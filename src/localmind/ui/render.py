"""Agent events -> Gradio chat messages (tool panels, reasoning, streamed answer)."""
from __future__ import annotations

import json
from pathlib import Path

from localmind.agent.orchestrator import AgentEvent

TOOL_ICONS = {
    "knowledge_search": "📚",
    "web_search": "🌐",
    "fetch_url": "🔗",
    "execute_python": "🐍",
    "read_file": "📄",
    "list_files": "🗂️",
    "open_document": "📂",
    "write_file": "✏️",
    "compile_latex": "🧾",
}
TOOL_STATUS = {
    "knowledge_search": "Searching your documents",
    "web_search": "Searching the web",
    "fetch_url": "Reading a page",
    "execute_python": "Running code",
    "read_file": "Reading a file",
    "list_files": "Looking through files",
    "open_document": "Opening a document",
    "write_file": "Writing a file",
    "compile_latex": "Typesetting the PDF",
}
STOPPED = "_Stopped._"


def tool_label(name: str, arguments: dict) -> str:
    icon = TOOL_ICONS.get(name, "🛠️")
    hint = arguments.get("query") or arguments.get("url") or arguments.get("path") or arguments.get("name") or arguments.get("directory") or ""
    if isinstance(hint, str) and hint:
        hint = hint if len(hint) <= 64 else hint[:61] + "…"
        return f"{icon} {name} · {hint}"
    return f"{icon} {name}"


def format_tool_result(raw: str) -> str:
    """Render a tool's JSON payload as something readable inside the collapsed panel."""
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return f"```\n{str(raw)[:2000]}\n```"

    if isinstance(data, dict):
        if "error" in data:
            hint = f"\n\n_{data['hint']}_" if data.get("hint") else ""
            return f"⚠️ {data['error']}{hint}"

        if "text" in data and "url" in data:  # fetch_url
            head = f"**[{data.get('title') or data['url']}]({data['url']})**"
            tail = "\n\n_…truncated_" if data.get("truncated") else ""
            return f"{head}\n\n{str(data['text'])[:1500]}{tail}"

        if "results" in data:
            hits, note = data["results"], data.get("note")
            if not hits:
                return f"_No results._\n\n{note}" if note else "_No results._"
            lines = []
            for hit in hits:
                if "url" in hit:
                    lines.append(f"**[{hit.get('title') or hit['url']}]({hit['url']})**  \n{hit.get('snippet', '')[:300]}")
                else:
                    page = hit.get("page")
                    where = str(hit.get("source", "?")) + (f" · p.{page}" if page not in (None, -1) else "")
                    lines.append(f"**{where}**  \n{str(hit.get('text', ''))[:400]}")
            if note:
                lines.append(f"_{note}_")
            return "\n\n".join(lines)

    if isinstance(data, list):
        lines = []
        for item in data[:10]:
            if isinstance(item, dict):
                lines.append(f"**{item.get('title') or item.get('path') or ''}**  \n{item.get('body') or item.get('href') or ''}")
            else:
                lines.append(str(item))
        return "\n\n".join(lines) if lines else "_Empty result._"

    return f"```json\n{json.dumps(data, indent=2)[:2000]}\n```"


def produced_files(tool_output: str) -> list[str]:
    """Files a tool result says it produced ({"files": [...]}), that exist on disk."""
    try:
        data = json.loads(tool_output)
    except (TypeError, ValueError):
        return []
    files = data.get("files") if isinstance(data, dict) else None
    return [f for f in files or [] if isinstance(f, str) and Path(f).is_file()]


class TurnRenderer:
    """Folds a stream of agent events into chat messages, mutating `history` in place."""

    def __init__(self, history: list[dict]):
        self.history = list(history)
        self.live: dict | None = None
        self.thinking: dict | None = None
        self.pending: dict[str, list[dict]] = {}
        self.status: str | None = "Thinking"
        self._stopped = False

    # -- helpers used outside the event stream ------------------------------------------------
    def panel(self, title: str) -> dict:
        panel = {"role": "assistant", "content": "", "metadata": {"title": title, "status": "pending"}}
        self.history.append(panel)
        return panel

    @staticmethod
    def finish_panel(panel: dict, content: str, duration: float | None = None) -> None:
        panel["content"] = content
        panel["metadata"]["status"] = "done"
        if duration is not None:
            panel["metadata"]["duration"] = round(duration, 1)

    def note(self, text: str) -> None:
        self.history.append({"role": "assistant", "content": "", "metadata": {"title": f"ℹ️ {text}", "status": "done"}})

    def error(self, text: str) -> None:
        self.history.append({"role": "assistant", "content": f"⚠️ **Something went wrong:** {text}"})
        self.status = None

    def stopped(self) -> None:
        """Settle an interrupted turn: no spinners left behind, and say it stopped."""
        if self._stopped:
            return
        self._stopped = True
        for message in self.history:
            meta = message.get("metadata") if isinstance(message, dict) else None
            if meta and meta.get("status") == "pending":
                meta["status"] = "done"
                message["content"] = message.get("content") or STOPPED
        if self.live is not None and self.live.get("content"):
            self.live["content"] = self.live["content"].rstrip() + "\n\n_— stopped_"
        else:
            last = self.history[-1] if self.history else None
            if last is None or last.get("role") == "user" or last.get("metadata"):
                self.history.append({"role": "assistant", "content": STOPPED})
        self.status = None

    # -- the event stream ---------------------------------------------------------------------
    def apply(self, event: AgentEvent) -> str | None:
        kind = event.kind
        if kind == "status":
            self.status = event.text
        elif kind == "notice":
            self.note(event.text)
        elif kind == "thinking_delta":
            if self.thinking is None:
                self.thinking = self.panel("💭 Reasoning")
            self.thinking["content"] = event.text
        elif kind == "thinking":
            if self.thinking is None:
                self.thinking = self.panel("💭 Reasoning")
            self.finish_panel(self.thinking, event.text)
            self.thinking = None
        elif kind == "answer_delta":
            if self.live is None:
                self.live = {"role": "assistant", "content": ""}
                self.history.append(self.live)
            self.live["content"] = event.text
            self.status = "Writing"
        elif kind == "discard_draft":
            if self.live is not None:
                self.history[:] = [m for m in self.history if m is not self.live]
                self.live = None
        elif kind == "tool_call":
            panel = self.panel(tool_label(event.name, event.arguments))
            self.pending.setdefault(event.name, []).append(panel)
            self.status = TOOL_STATUS.get(event.name, "Using tools")
        elif kind == "tool_result":
            queue = self.pending.get(event.name) or []
            panel = queue.pop(0) if queue else self.panel(tool_label(event.name, {}))
            self.finish_panel(panel, format_tool_result(event.text), event.duration)
            for path in produced_files(event.text):
                # A file a tool made (a compiled CV, say) shows up in the chat to download.
                self.history.append({"role": "assistant", "content": {"path": path}})
        elif kind == "answer":
            if self.live is None:
                self.live = {"role": "assistant", "content": ""}
                self.history.append(self.live)
            self.live["content"] = event.text
            self.live = None
            self.status = None
        elif kind == "error":
            self.error(event.text)
        return self.status
