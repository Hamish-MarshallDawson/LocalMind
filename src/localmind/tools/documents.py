"""Documents the model can open, write and typeset: the tools behind "tailor my CV to this job".

- `open_document` returns the *original* of a knowledge-base document (the real LaTeX source of a
  CV, not the text chunks search returns), if the chat's scope lets it see that document.
- `write_file` saves into the chat's own output folder, data/outputs/<chat id>/, and nowhere else.
- `compile_latex` turns a .tex file there into a PDF, using the TeX already on this PC (latexmk,
  from MiKTeX or TeX Live) or, failing that, Tectonic, downloaded once and checked against its
  published SHA-256. The PDF appears in the chat as a file you can download.
"""
from __future__ import annotations

import contextvars
import hashlib
import io
import json
import logging
import re
import shutil
import subprocess
import zipfile
from pathlib import Path

import httpx

from localmind.config import AppConfig

logger = logging.getLogger(__name__)

# The chat whose turn is running on this thread: where its files go.
current_chat: contextvars.ContextVar[str] = contextvars.ContextVar("current_chat", default="")

TEXT_TYPES = {".tex", ".bib", ".cls", ".sty", ".txt", ".md", ".csv", ".json", ".html", ".yaml", ".yml"}
SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.()-]{0,120}$")

# Tectonic, only used when no TeX is installed. Pinned to a release and its published digest.
TECTONIC = {
    "version": "0.17.0",
    "url": "https://github.com/tectonic-typesetting/tectonic/releases/download/tectonic%400.17.0/tectonic-0.17.0-x86_64-pc-windows-msvc.zip",
    "sha256": "f61ce51f0b0ade1015b7de7ef368541c5424e9756ecbd0d7af97d6d48030845f",
}


def data_root(config: AppConfig) -> Path:
    return Path(config.storage.conversations_db).resolve().parent


def originals_dir(config: AppConfig) -> Path:
    return Path(config.ingest.docs_dir).resolve()


def outputs_dir(config: AppConfig, cid: str | None = None) -> Path:
    base = data_root(config) / "outputs"
    return base / (cid or "scratch")


def keep_original(config: AppConfig, path: Path, name: str) -> Path | None:
    """Keep a copy of an indexed file so the model can later open the real thing."""
    try:
        target = originals_dir(config) / Path(name).name
        target.parent.mkdir(parents=True, exist_ok=True)
        if Path(path).resolve() != target:
            shutil.copyfile(path, target)
        return target
    except OSError as e:
        logger.warning("Couldn't keep a copy of %s: %s", name, e)
        return None


def _safe_name(name: str) -> str:
    name = Path(str(name or "").replace("\\", "/")).name
    if not SAFE_NAME.match(name) or name in (".", ".."):
        raise ValueError(f"{name!r} isn't a usable file name: letters, digits, spaces, - _ . ( ) only.")
    return name


# ---------------------------------------------------------------------------- TeX engines

def _tectonic_path(config: AppConfig) -> Path:
    return data_root(config) / "tools" / f"tectonic-{TECTONIC['version']}" / "tectonic.exe"


def ensure_tectonic(config: AppConfig) -> Path:
    exe = _tectonic_path(config)
    if exe.exists():
        return exe
    logger.info("Downloading Tectonic %s (no TeX found on this PC)", TECTONIC["version"])
    response = httpx.get(TECTONIC["url"], follow_redirects=True, timeout=120)
    response.raise_for_status()
    digest = hashlib.sha256(response.content).hexdigest()
    if digest != TECTONIC["sha256"]:
        raise RuntimeError(f"Tectonic download didn't match its published checksum ({digest}); not using it.")
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        member = next(n for n in archive.namelist() if n.lower().endswith("tectonic.exe"))
        exe.parent.mkdir(parents=True, exist_ok=True)
        exe.write_bytes(archive.read(member))
    return exe


def latex_command(config: AppConfig, tex: Path) -> list[str]:
    """The best way to build this file on this PC."""
    source = tex.read_text(encoding="utf-8", errors="replace")
    unicode_engine = bool(re.search(r"\\usepackage(\[[^]]*\])?\{(fontspec|unicode-math)\}", source))
    engine = config.tools.latex.engine
    if engine in ("auto", "latexmk") and shutil.which("latexmk"):
        flag = "-xelatex" if unicode_engine else "-pdf"
        return ["latexmk", flag, "-interaction=nonstopmode", "-halt-on-error", "-file-line-error", tex.name]
    if engine == "auto" and shutil.which("xelatex" if unicode_engine else "pdflatex"):
        program = "xelatex" if unicode_engine else "pdflatex"
        return [program, "-interaction=nonstopmode", "-halt-on-error", "-file-line-error", tex.name]
    return [str(ensure_tectonic(config)), "--keep-logs", tex.name]


def _latex_errors(log: str) -> list[str]:
    """The lines of a TeX log worth showing the model: errors and the lines just after them."""
    lines = log.splitlines()
    found = []
    for i, line in enumerate(lines):
        if line.startswith("!") or re.match(r"^[^:\s]+\.tex:\d+:", line) or line.lower().startswith("error"):
            found.append(" ".join(part.strip() for part in lines[i:i + 3] if part.strip()))
    return found[:8]


# ---------------------------------------------------------------------------- the tools

MIN_TAILORING_EDITS = 3  # fewer changed lines than this, on a document opened to adapt, is a token edit


def compare_to_original(original: str, new: str, limit: int = 14) -> dict:
    """Which lines of a saved file differ from the original it was based on: facts the model can
    report, instead of recalling (and overstating) what it thinks it changed."""
    import difflib

    old_lines, new_lines = original.splitlines(), new.splitlines()
    removed, added = [], []
    for line in difflib.unified_diff(old_lines, new_lines, lineterm="", n=0):
        if line.startswith("-") and not line.startswith("---") and line[1:].strip():
            removed.append(line[1:].strip())
        elif line.startswith("+") and not line.startswith("+++") and line[1:].strip():
            added.append(line[1:].strip())
    return {
        "lines_changed": max(len(removed), len(added)),
        "removed": [r[:160] for r in removed[:limit]],
        "added": [a[:160] for a in added[:limit]],
    }


def register_document_tools(registry, config: AppConfig, rag_engine) -> None:
    from localmind.rag.sections import current_scope

    # The last original each chat opened, so a file saved from it can be compared against it.
    opened: dict[str, tuple[str, str]] = {}

    def visible(name: str) -> bool:
        allowed = rag_engine.sections.visible_sources(current_scope.get(), rag_engine.list_sources())
        return allowed is None or name in allowed

    def open_document(name: str) -> str:
        name = Path(str(name)).name
        if name not in rag_engine.list_sources():
            return json.dumps({"error": f"No document called {name!r}.", "documents": sorted(filter(visible, rag_engine.list_sources()))})
        if not visible(name):
            return json.dumps({"error": f"{name} is in a knowledge-base section this chat can't see."})
        original = originals_dir(config) / name
        if not original.exists():
            return json.dumps({"error": f"No original of {name} was kept (it was indexed before originals were saved). Re-index it to open it."})
        if original.suffix.lower() in TEXT_TYPES:
            text = original.read_text(encoding="utf-8", errors="replace")
        elif original.suffix.lower() == ".pdf":
            import pymupdf

            with pymupdf.open(original) as doc:
                text = "\n\n".join(page.get_text() for page in doc)
        else:
            return json.dumps({"error": f"{name} isn't a text document; use knowledge_search for its contents."})
        opened[current_chat.get()] = (name, text)
        return json.dumps({"name": name, "section": rag_engine.sections.section_of(name), "content": text[:60_000]})

    def write_file(name: str, content: str) -> str:
        try:
            name = _safe_name(name)
        except ValueError as e:
            return json.dumps({"error": str(e)})
        if Path(name).suffix.lower() not in TEXT_TYPES:
            return json.dumps({"error": f"Only text files can be written ({', '.join(sorted(TEXT_TYPES))})."})
        folder = outputs_dir(config, current_chat.get())
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / name
        target.write_text(content, encoding="utf-8")
        result = {"saved": str(target), "bytes": len(content.encode("utf-8"))}
        base = opened.get(current_chat.get())
        if base and Path(base[0]).suffix.lower() == target.suffix.lower():
            changes = compare_to_original(base[1], content)
            result["compared_to"] = base[0]
            result.update(changes)
            result["note"] = (
                "These are the only differences from the original: describe exactly these to the user, nothing more."
                if changes["lines_changed"] >= MIN_TAILORING_EDITS else
                f"Only {changes['lines_changed']} line(s) differ from {base[0]}. If the task was to tailor or rewrite "
                "it, that's a token edit: make the substantive changes asked for, then write_file again."
            )
        return json.dumps(result)

    def compile_latex(name: str) -> str:
        try:
            name = _safe_name(name)
        except ValueError as e:
            return json.dumps({"error": str(e)})
        folder = outputs_dir(config, current_chat.get())
        tex = folder / name
        if tex.suffix.lower() != ".tex" or not tex.exists():
            return json.dumps({"error": f"No {name} in this chat's files. Save it with write_file first."})
        try:
            command = latex_command(config, tex)
            result = subprocess.run(
                command, cwd=folder, capture_output=True, text=True, errors="replace",
                timeout=config.tools.latex.timeout_seconds,
                stdin=subprocess.DEVNULL,  # never wait on a prompt (e.g. to install a package)
            )
        except subprocess.TimeoutExpired:
            return json.dumps({"error": f"LaTeX took longer than {config.tools.latex.timeout_seconds}s and was stopped."})
        except Exception as e:  # noqa: BLE001
            return json.dumps({"error": f"Couldn't run LaTeX: {e}"})
        pdf = tex.with_suffix(".pdf")
        log_file = tex.with_suffix(".log")
        log = (log_file.read_text(encoding="utf-8", errors="replace") if log_file.exists() else "") + result.stdout + result.stderr
        if result.returncode != 0 or not pdf.exists():
            return json.dumps({"error": "LaTeX failed.", "details": _latex_errors(log) or log[-2000:].splitlines()[-15:]})
        pages = None
        try:
            import pymupdf

            with pymupdf.open(pdf) as doc:
                pages = doc.page_count
        except Exception:  # noqa: BLE001
            pass
        return json.dumps({"pdf": str(pdf), "pages": pages, "engine": Path(command[0]).stem, "files": [str(pdf)]})

    registry.register(
        name="open_document",
        description=(
            "Open the original of a knowledge-base document by name, e.g. the full LaTeX source of a CV. "
            "Use knowledge_search to find things; use this when you need a whole document to edit it."
        ),
        parameters={"name": {"type": "string", "description": "The document's name, as knowledge_search reports it"}},
        function=open_document,
        required_params=["name"],
    )
    registry.register(
        name="write_file",
        description=(
            "Save a text file (e.g. cv.tex, cover-letter.md) into this chat's own output folder. "
            "Overwrites a file of the same name. Always write the complete file."
        ),
        parameters={
            "name": {"type": "string", "description": "File name only, e.g. cv-barclays.tex"},
            "content": {"type": "string", "description": "The full file contents"},
        },
        function=write_file,
        required_params=["name", "content"],
    )
    registry.register(
        name="compile_latex",
        description=(
            "Typeset a .tex file saved with write_file into a PDF, which the user can then download. "
            "If it fails, read the errors, fix the file with write_file, and compile again."
        ),
        parameters={"name": {"type": "string", "description": "The .tex file name, e.g. cv-barclays.tex"}},
        function=compile_latex,
        required_params=["name"],
    )
