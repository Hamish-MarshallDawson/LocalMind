"""Skills: folders of instructions (and optional files) that teach the model a task, in the same
format as Claude's Agent Skills. Each has a SKILL.md with a name and description up front:

    ---
    name: latex-cv
    description: Tailor a LaTeX CV to a job description.
    ---
    (instructions...)

The model sees every skill's name and description in its system prompt, and calls `use_skill` to
read the full instructions only when a task calls for them, so a dozen installed skills cost a few
lines of context, not a few thousand.
"""
from __future__ import annotations

import io
import json
import logging
import re
import shutil
import threading
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse

import httpx
import yaml

logger = logging.getLogger(__name__)

NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
MAX_DOWNLOAD = 25 * 1024 * 1024
MAX_FILES = 500
TEXT_FILE = re.compile(r"\.(md|txt|py|js|ts|sh|ps1|json|ya?ml|toml|tex|csv|html|xml|css|cfg|ini)$", re.I)


class SkillError(ValueError):
    pass


@dataclass
class Skill:
    name: str
    description: str
    path: Path
    source: str = ""

    def as_dict(self) -> dict:
        return {"name": self.name, "description": self.description, "source": self.source}


def parse_skill_md(text: str) -> tuple[dict, str]:
    """Split SKILL.md into its frontmatter (a dict) and the instructions that follow it."""
    match = re.match(r"^﻿?---\s*\n(.*?)\n---\s*\n?(.*)$", text, re.S)
    if not match:
        raise SkillError("SKILL.md must start with a --- frontmatter block holding name and description.")
    try:
        meta = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError as e:
        raise SkillError(f"SKILL.md frontmatter isn't valid YAML: {e}") from e
    if not isinstance(meta, dict):
        raise SkillError("SKILL.md frontmatter must be a set of key: value lines.")
    name = str(meta.get("name") or "").strip()
    description = " ".join(str(meta.get("description") or "").split())
    if not NAME.match(name):
        raise SkillError(f"Skill name {name!r} must be lower-case letters, digits and hyphens (up to 64).")
    if not description:
        raise SkillError("A skill needs a description, so the model knows when to use it.")
    meta["name"], meta["description"] = name, description[:1024]
    return meta, match.group(2)


def _github_zip(url: str) -> tuple[str, str]:
    """(zip URL, folder within the archive) for a github.com repo or tree link."""
    parts = [p for p in urlparse(url).path.split("/") if p]
    if len(parts) < 2:
        raise SkillError("Expected a link like https://github.com/owner/repo/tree/main/path/to/skill")
    owner, repo = parts[0], parts[1].removesuffix(".git")
    ref, sub = "HEAD", ""
    if len(parts) >= 4 and parts[2] in ("tree", "blob"):
        ref, sub = parts[3], "/".join(parts[4:])
        if sub.endswith("SKILL.md"):
            sub = sub[: -len("SKILL.md")].rstrip("/")
    return f"https://codeload.github.com/{owner}/{repo}/zip/{ref}", sub


class SkillLibrary:
    def __init__(self, directory: str | Path, fetch=None):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self._fetch = fetch or self._http_get
        self._lock = threading.Lock()

    @staticmethod
    def _http_get(url: str) -> bytes:
        with httpx.stream("GET", url, follow_redirects=True, timeout=60) as response:
            response.raise_for_status()
            chunks, size = [], 0
            for chunk in response.iter_bytes():
                size += len(chunk)
                if size > MAX_DOWNLOAD:
                    raise SkillError("That download is over 25 MB, which is too big for a skill.")
                chunks.append(chunk)
            return b"".join(chunks)

    # ------------------------------------------------------------------ reading
    def list(self) -> list[Skill]:
        skills = []
        for folder in sorted(p for p in self.directory.iterdir() if p.is_dir()):
            skill_md = folder / "SKILL.md"
            if not skill_md.exists():
                continue
            try:
                meta, _ = parse_skill_md(skill_md.read_text(encoding="utf-8"))
            except (SkillError, OSError) as e:
                logger.warning("Skipping skill in %s: %s", folder, e)
                continue
            source = ""
            origin = folder / ".source"
            if origin.exists():
                source = origin.read_text(encoding="utf-8").strip()
            skills.append(Skill(meta["name"], meta["description"], folder, source))
        return skills

    def get(self, name: str) -> Skill | None:
        return next((s for s in self.list() if s.name == name), None)

    def prompt_block(self) -> str:
        skills = self.list()
        if not skills:
            return ""
        lines = "\n".join(f"- {s.name}: {s.description}" for s in skills)
        return (
            "\n\nSKILLS: installed instructions for particular kinds of task. When a request matches "
            "one, call use_skill with its name first and follow what it says.\n" + lines + "\n"
        )

    # ------------------------------------------------------------------ installing
    def install(self, source: str) -> Skill:
        """Install from a GitHub repo/folder link, a .zip link, or a local folder."""
        source = source.strip()
        if Path(source).is_dir():
            return self._install_folder(Path(source), source)
        parsed = urlparse(source)
        if parsed.scheme not in ("https", "http"):
            raise SkillError("Give a GitHub link, a link to a .zip, or a local folder.")
        if parsed.netloc.lower() in ("github.com", "www.github.com"):
            zip_url, sub = _github_zip(source)
        else:
            zip_url, sub = source, ""
        return self._install_zip(self._fetch(zip_url), sub, source)

    def _install_zip(self, data: bytes, sub: str, source: str) -> Skill:
        try:
            archive = zipfile.ZipFile(io.BytesIO(data))
        except zipfile.BadZipFile as e:
            raise SkillError("That link didn't lead to a zip archive.") from e
        names = archive.namelist()
        # GitHub archives wrap everything in "<repo>-<ref>/"; a plain zip may or may not.
        top = names[0].split("/")[0] + "/" if names and all(n.startswith(names[0].split("/")[0] + "/") for n in names) else ""
        prefix = top + (sub.strip("/") + "/" if sub else "")
        if prefix + "SKILL.md" not in names:
            candidates = sorted({n.rsplit("/", 1)[0] for n in names if n.endswith("/SKILL.md")})
            hint = f" Skills in this archive: {', '.join(c.removeprefix(top) for c in candidates[:10])}" if candidates else ""
            raise SkillError(f"No SKILL.md at {sub or 'the top level'}.{hint}")
        members = [n for n in names if n.startswith(prefix) and not n.endswith("/")]
        if len(members) > MAX_FILES:
            raise SkillError(f"That skill has over {MAX_FILES} files.")
        meta, _ = parse_skill_md(archive.read(prefix + "SKILL.md").decode("utf-8", errors="replace"))
        with self._lock:
            staging = self.directory / f".installing-{meta['name']}"
            shutil.rmtree(staging, ignore_errors=True)
            for member in members:
                relative = PurePosixPath(member[len(prefix):])
                if relative.is_absolute() or ".." in relative.parts:
                    raise SkillError(f"Refusing an unsafe path in the archive: {member}")
                target = staging / Path(*relative.parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.read(member))
            return self._commit(staging, meta["name"], source)

    def _install_folder(self, folder: Path, source: str) -> Skill:
        meta, _ = parse_skill_md((folder / "SKILL.md").read_text(encoding="utf-8"))
        with self._lock:
            staging = self.directory / f".installing-{meta['name']}"
            shutil.rmtree(staging, ignore_errors=True)
            shutil.copytree(folder, staging)
            return self._commit(staging, meta["name"], source)

    def _commit(self, staging: Path, name: str, source: str) -> Skill:
        (staging / ".source").write_text(source, encoding="utf-8")
        final = self.directory / name
        shutil.rmtree(final, ignore_errors=True)  # reinstalling replaces the old copy
        staging.rename(final)
        logger.info("Installed skill %s from %s", name, source)
        skill = self.get(name)
        assert skill is not None
        return skill

    def remove(self, name: str) -> bool:
        skill = self.get(name)
        if skill is None:
            return False
        shutil.rmtree(skill.path)
        return True


def register_skill_tools(registry, library: SkillLibrary) -> None:
    def use_skill(name: str) -> str:
        skill = library.get(str(name).strip())
        if skill is None:
            return json.dumps({"error": f"No skill called {name!r}.", "installed": [s.name for s in library.list()]})
        _, instructions = parse_skill_md((skill.path / "SKILL.md").read_text(encoding="utf-8"))
        files = sorted(
            str(p.relative_to(skill.path)).replace("\\", "/")
            for p in skill.path.rglob("*")
            if p.is_file() and p.name not in ("SKILL.md", ".source")
        )
        return json.dumps({
            "skill": skill.name,
            "instructions": instructions[:40_000],
            "files": files[:200],
            "folder": str(skill.path),
            "note": "Read a listed file with read_skill_file. Scripts can be run with execute_python (e.g. via subprocess) from the folder above.",
        })

    def read_skill_file(name: str, path: str) -> str:
        skill = library.get(str(name).strip())
        if skill is None:
            return json.dumps({"error": f"No skill called {name!r}."})
        target = (skill.path / path).resolve()
        if not target.is_relative_to(skill.path.resolve()) or not target.is_file():
            return json.dumps({"error": f"{path} isn't a file in the {skill.name} skill."})
        if not TEXT_FILE.search(target.name):
            return json.dumps({"error": f"{path} isn't a text file.", "size": target.stat().st_size})
        return json.dumps({"path": path, "content": target.read_text(encoding="utf-8", errors="replace")[:60_000]})

    registry.register(
        name="use_skill",
        description="Load an installed skill's full instructions (and list its files) before doing a task it covers.",
        parameters={"name": {"type": "string", "description": "The skill's name, from the SKILLS list"}},
        function=use_skill,
        required_params=["name"],
    )
    registry.register(
        name="read_skill_file",
        description="Read one of a skill's own files (a template, reference or script), as listed by use_skill.",
        parameters={
            "name": {"type": "string", "description": "The skill's name"},
            "path": {"type": "string", "description": "The file's path inside the skill, e.g. templates/cv.tex"},
        },
        function=read_skill_file,
        required_params=["name", "path"],
    )
