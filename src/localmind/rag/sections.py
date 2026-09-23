"""Sections of the knowledge base, and who can see them.

Every document belongs to one section. A section is either **shared** (every chat can search it,
like a general CV) or **private** (only chats scoped to it can, like material for one Barclays
application). A chat scoped to "Barclays" searches Barclays plus every shared section; a chat
with no scope searches everything.

Kept beside the vector store as a small JSON file, so documents never need re-indexing to move
between sections.
"""
from __future__ import annotations

import contextvars
import json
import threading
from pathlib import Path

DEFAULT_SECTION = "General"
ALL = ""  # the scope that sees every section

# The scope of the turn running on this thread; the knowledge_search tool reads it.
current_scope: contextvars.ContextVar[str] = contextvars.ContextVar("kb_scope", default=ALL)


class SectionError(ValueError):
    pass


class KnowledgeSections:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._lock = threading.Lock()
        self._data = self._load()

    def _load(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        data.setdefault("sections", {})
        data.setdefault("documents", {})
        data["sections"].setdefault(DEFAULT_SECTION, {"shared": True})
        return data

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._data, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(self.path)

    # ------------------------------------------------------------------ sections
    def sections(self) -> list[dict]:
        with self._lock:
            counts: dict[str, int] = {}
            for section in self._data["documents"].values():
                counts[section] = counts.get(section, 0) + 1
            return [
                {"name": name, "shared": bool(info.get("shared")), "documents": counts.get(name, 0)}
                for name, info in sorted(self._data["sections"].items(), key=lambda kv: (kv[0] != DEFAULT_SECTION, kv[0].lower()))
            ]

    def names(self) -> list[str]:
        return [s["name"] for s in self.sections()]

    def create(self, name: str, shared: bool = False) -> None:
        name = " ".join((name or "").split())
        if not name or len(name) > 60:
            raise SectionError("A section needs a name of up to 60 characters.")
        with self._lock:
            if any(existing.lower() == name.lower() for existing in self._data["sections"]):
                raise SectionError(f"There's already a section called {name!r}.")
            self._data["sections"][name] = {"shared": bool(shared)}
            self._save()

    def set_shared(self, name: str, shared: bool) -> None:
        with self._lock:
            if name not in self._data["sections"]:
                raise SectionError(f"No section called {name!r}.")
            self._data["sections"][name]["shared"] = bool(shared)
            self._save()

    def delete(self, name: str) -> int:
        """Remove a section; its documents move to General rather than disappearing."""
        if name == DEFAULT_SECTION:
            raise SectionError("General can't be deleted: it's where unsorted documents live.")
        with self._lock:
            if self._data["sections"].pop(name, None) is None:
                raise SectionError(f"No section called {name!r}.")
            moved = [doc for doc, section in self._data["documents"].items() if section == name]
            for doc in moved:
                self._data["documents"][doc] = DEFAULT_SECTION
            self._save()
            return len(moved)

    # ------------------------------------------------------------------ documents
    def section_of(self, source: str) -> str:
        with self._lock:
            section = self._data["documents"].get(source, DEFAULT_SECTION)
            return section if section in self._data["sections"] else DEFAULT_SECTION

    def assign(self, source: str, section: str) -> None:
        with self._lock:
            if section not in self._data["sections"]:
                raise SectionError(f"No section called {section!r}.")
            self._data["documents"][source] = section
            self._save()

    def forget(self, source: str) -> None:
        with self._lock:
            if self._data["documents"].pop(source, None) is not None:
                self._save()

    def is_shared(self, section: str) -> bool:
        with self._lock:
            return bool(self._data["sections"].get(section, {}).get("shared"))

    def visible_sections(self, scope: str) -> set[str] | None:
        """Sections a chat with this scope may search; None means all of them."""
        if not scope:
            return None
        with self._lock:
            visible = {name for name, info in self._data["sections"].items() if info.get("shared")}
            if scope in self._data["sections"]:
                visible.add(scope)
            return visible

    def visible_sources(self, scope: str, all_sources: list[str]) -> set[str] | None:
        """Documents a chat with this scope may search; None means no restriction."""
        sections = self.visible_sections(scope)
        if sections is None:
            return None
        return {source for source in all_sources if self.section_of(source) in sections}

    def describe_scope(self, scope: str) -> str:
        sections = self.visible_sections(scope)
        if sections is None:
            return "all sections"
        return ", ".join(sorted(sections)) or "no sections"
