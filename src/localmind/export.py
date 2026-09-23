"""Export a conversation to PDF.

Uses PyMuPDF's Story layout engine (already a dependency for PDF ingestion): chat messages are
rendered from Markdown to HTML and flowed across A4 pages, so answers keep their tables, lists,
code blocks and links. No browser or external converter is needed.
"""
from __future__ import annotations

import datetime as dt
import html
import io
import os
import re
from pathlib import Path

import pymupdf as fitz
from markdown_it import MarkdownIt

_md = MarkdownIt("commonmark", {"html": False, "linkify": False}).enable(["table", "strikethrough"])

# Emoji have no glyphs in document fonts and would print as empty boxes.
# Leading whitespace goes too, so "Edinburgh \uD83C\uDFAF." becomes "Edinburgh." not "Edinburgh .".
_EMOJI = re.compile(
    "\\s*[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F\u200D\u2B50\u2B06\u2194-\u21AA\u23E9-\u23FA\u24C2\u2139\u231A\u231B\u2328]"
)

PAGE = fitz.paper_rect("a4")
MARGIN = (54, 58, 54, 64)  # left, top, right, bottom in points

# Palette (matches the app): Deep Space Blue, Strong Cyan, Ash Grey, Parchment, Soft Apricot.
CSS = """
* { font-family: body; }
body { font-size: 10.5pt; line-height: 1.45; color: #12263A; }
h1.doc-title { font-size: 18pt; margin: 0 0 2pt 0; color: #12263A; }
p.meta { font-size: 8.5pt; color: #4F6272; margin: 0 0 14pt 0; }
div.user { background-color: #F4D1AE; padding: 7pt 10pt; margin: 10pt 0 6pt 60pt; border-radius: 6pt; }
div.user p { margin: 0 0 4pt 0; }
div.who { font-size: 7.5pt; font-weight: bold; color: #4F6272; margin: 8pt 0 2pt 0; text-transform: uppercase; }
div.assistant { margin: 0 0 6pt 0; }
div.assistant p { margin: 0 0 6pt 0; }
div.tool { font-size: 8.5pt; color: #026A6E; margin: 3pt 0; padding: 2pt 0 2pt 6pt; border-left: 2pt solid #06BCC1; }
div.notice { font-size: 8.5pt; color: #4F6272; font-style: italic; margin: 3pt 0; }
code { font-family: mono; font-size: 9pt; background-color: #EFE6E1; }
pre { font-family: mono; font-size: 8.5pt; background-color: #F6F0EC; padding: 6pt; }
table { border-collapse: collapse; margin: 4pt 0 8pt 0; }
th, td { border: 0.6pt solid #C5D8D1; padding: 3pt 5pt; font-size: 9pt; }
th { background-color: #EFE6E1; font-weight: bold; }
a { color: #026A6E; }
ul, ol { margin: 0 0 6pt 0; }
b, strong, th { font-weight: bold; }
"""


def _font_archive() -> tuple[fitz.Archive | None, str]:
    """Unicode-capable fonts for bullets, dashes and non-Latin text. Falls back to built-ins."""
    windows = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    candidates = [
        (windows, "segoeui.ttf", "segoeuib.ttf", "segoeuii.ttf", "consola.ttf"),
        (Path("/usr/share/fonts/truetype/dejavu"), "DejaVuSans.ttf", "DejaVuSans-Bold.ttf", "DejaVuSans-Oblique.ttf", "DejaVuSansMono.ttf"),
    ]
    for folder, regular, bold, italic, mono in candidates:
        if (folder / regular).exists():
            archive = fitz.Archive(str(folder))
            faces = [
                f"@font-face {{ font-family: body; src: url({regular}); }}",
                f"@font-face {{ font-family: body; src: url({bold}); font-weight: bold; }}" if (folder / bold).exists() else "",
                f"@font-face {{ font-family: body; src: url({italic}); font-style: italic; }}" if (folder / italic).exists() else "",
                f"@font-face {{ font-family: mono; src: url({mono}); }}" if (folder / mono).exists() else "",
            ]
            return archive, "\n".join(f for f in faces if f)
    return None, ""


def _text_of(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, dict):
        path = content.get("path") or (content.get("file") or {}).get("path")
        return f"[image: {Path(path).name}]" if path else ""
    if isinstance(content, list):
        return "\n".join(_text_of(part.get("text") if isinstance(part, dict) and part.get("type") == "text" else part) for part in content)
    return str(content or "")


def _clean(text: str) -> str:
    return _EMOJI.sub("", text).strip()


def conversation_html(title: str, history: list[dict], model_label: str = "", include_reasoning: bool = False) -> str:
    parts = [
        f"<h1 class='doc-title'>{html.escape(_clean(title))}</h1>",
        f"<p class='meta'>Exported {dt.datetime.now():%d %B %Y, %H:%M}"
        + (f" &middot; {html.escape(model_label)}" if model_label else "")
        + " &middot; LocalMind</p>",
    ]
    last_role = None
    for message in history:
        if not isinstance(message, dict):
            continue
        role = message.get("role")
        meta = message.get("metadata") or {}
        text = _text_of(message.get("content"))

        if meta.get("title"):
            label = _clean(str(meta["title"]))
            if label.lower().startswith("reasoning"):
                if include_reasoning and text:
                    parts.append(f"<div class='tool'><b>Reasoning</b><br/>{_md.render(_clean(text))}</div>")
                continue
            if not text or text.strip() in ("", "_Stopped._"):
                parts.append(f"<div class='notice'>{html.escape(label)}</div>")
                continue
            duration = f" ({meta['duration']}s)" if meta.get("duration") is not None else ""
            parts.append(f"<div class='tool'>Used {html.escape(label)}{duration}</div>")
            continue

        if role == "user":
            if last_role != "user":
                parts.append("<div class='who'>You</div>")
            parts.append(f"<div class='user'>{_md.render(_clean(text))}</div>")
        elif role == "assistant" and text.strip():
            if last_role != "assistant":
                parts.append("<div class='who'>LocalMind</div>")
            parts.append(f"<div class='assistant'>{_md.render(_clean(text))}</div>")
        last_role = role
    return "<body>" + "\n".join(parts) + "</body>"


def export_pdf(path: str | Path, title: str, history: list[dict], model_label: str = "", include_reasoning: bool = False) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    archive, faces = _font_archive()
    story = fitz.Story(html=conversation_html(title, history, model_label, include_reasoning), user_css=faces + CSS, archive=archive)

    left, top, right, bottom = MARGIN
    where = fitz.Rect(PAGE.x0 + left, PAGE.y0 + top, PAGE.x1 - right, PAGE.y1 - bottom)
    # Lay out in memory and write the file once: re-opening and replacing a file PyMuPDF has
    # just written fails on Windows while its handle lingers.
    buffer = io.BytesIO()
    writer = fitz.DocumentWriter(buffer)
    more = True
    while more:
        device = writer.begin_page(PAGE)
        more, _ = story.place(where)
        story.draw(device)
        writer.end_page()
    writer.close()

    # Page footers need the final page count, so add them in a second pass.
    doc = fitz.open(stream=buffer.getvalue(), filetype="pdf")
    footer = _clean(title)[:80]
    for number, page in enumerate(doc, start=1):
        y = PAGE.y1 - bottom / 2
        page.insert_text((left, y), footer, fontsize=7.5, color=(0.31, 0.38, 0.45))
        label = f"{number} / {doc.page_count}"
        page.insert_text((PAGE.x1 - right - fitz.get_text_length(label, fontsize=7.5), y), label, fontsize=7.5, color=(0.31, 0.38, 0.45))
    # Embed only the glyphs used: full Segoe UI faces would make a two-page chat ~3 MB.
    doc.subset_fonts()
    doc.save(str(path), garbage=3, deflate=True)
    doc.close()
    return path


def safe_filename(title: str) -> str:
    stem = re.sub(r"[^\w\- ]+", "", _clean(title)).strip().replace(" ", "_")[:60] or "chat"
    return f"{stem}_{dt.datetime.now():%Y%m%d-%H%M}.pdf"
