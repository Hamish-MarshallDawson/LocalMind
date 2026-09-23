from __future__ import annotations

import datetime as dt
import html
import logging
import threading
import time
from pathlib import Path

import gradio as gr

from localmind.agent.messages import normalize_transcript
from localmind.agent.orchestrator import Agent
from localmind.export import export_pdf, safe_filename
from localmind.extensions import Extensions, McpHub
from localmind.llm.anthropic_backend import credentials_hint
from localmind.llm.kvcache import KV_CACHE_TYPES, kv_type
from localmind.llm.types import ModelSpec
from localmind.metrics import gpu_stats
from localmind.rag.engine import RAGEngine
from localmind.rag.sections import DEFAULT_SECTION, SectionError
from localmind.storage import DEFAULT_TITLE, ConversationStore
from localmind.voice import VoiceEngine

from .theme import CSS, JS, THEME  # noqa: F401 - re-exported for the CLI
from .tasks import TaskQueue, item_from_file, split_items
from .turns import IMAGE_EXTS, TurnBusy, TurnManager

logger = logging.getLogger(__name__)

STREAM_INTERVAL = 0.05  # seconds between UI repaints while tokens stream
HUD_INTERVAL = 2.0  # seconds between GPU readings

STARTERS = [
    {"text": "Summarise my CV and point out its three weakest spots"},
    {"text": "Which graduate roles in Edinburgh suit my background?"},
    {"text": "What's making the news in Scotland today?"},
    {"text": "Explain QLoRA to me like I'm a product manager"},
]
HERO = (
    "<div class='lm-hero'><div class='lm-hero-mark'>LM</div>"
    "<h2>What are we working on?</h2>"
    "<p>Turn on <b>Web search</b> or <b>Knowledge base</b> below to make sure they're used.</p></div>"
)
VIEWS = ("chat", "kb", "search", "tasks", "tools")
TASK_INSTRUCTIONS_HINT = (
    "e.g. Using my CV (open_document the .tex original), tailor it to the job description below: "
    "reorder and rewrite bullets to match the requirements, keep the layout, British English. "
    "Save it with write_file as cv-<company>.tex and compile_latex it."
)
STATE_ICONS = {"waiting": "⏳", "running": "▶️", "done": "✅", "failed": "⚠️", "cancelled": "⏹️"}
NO_SELECTION = "Select a document to remove it"


# ---------------------------------------------------------------------------- helpers

def _composer_busy():
    return gr.MultimodalTextbox(value=None, submit_btn=False, stop_btn=True)


def _composer_ready():
    return gr.MultimodalTextbox(submit_btn=True, stop_btn=False)


def _group_label(ts: float, today: dt.date) -> str:
    age = (today - dt.datetime.fromtimestamp(ts).date()).days
    if age <= 0:
        return "Today"
    if age == 1:
        return "Yesterday"
    if age < 7:
        return "Previous 7 days"
    if age < 30:
        return "Previous 30 days"
    return "Older"


def _file_path(item) -> Path:
    if isinstance(item, dict):
        return Path(item.get("path") or item.get("name") or "")
    return Path(getattr(item, "path", None) or getattr(item, "name", None) or item)


def _short(n: float) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M".replace(".0M", "M")
    if n >= 1000:
        return f"{n / 1000:.1f}K".replace(".0K", "K")
    return str(int(n))


def _chip(on: bool, *, locked: bool = False, disabled: bool = False) -> list[str]:
    classes = ["lm-chip"]
    if on:
        classes.append("lm-chip-on")
    if locked:
        classes.append("lm-chip-locked")
    if disabled:
        classes.append("lm-chip-disabled")
    return classes


def _thinking_button(spec: ModelSpec, on: bool):
    if spec.thinking == "none":
        return gr.Button("Thinking", interactive=False, elem_classes=_chip(False, disabled=True))
    if spec.thinking == "always":
        return gr.Button("Thinking", interactive=False, elem_classes=_chip(True, locked=True))
    return gr.Button("Thinking", interactive=True, elem_classes=_chip(on))


def _variant_cached(repo: str | None) -> bool:
    if not repo:
        return True
    try:
        from huggingface_hub import try_to_load_from_cache

        return isinstance(try_to_load_from_cache(repo, "config.json"), str)
    except Exception:  # noqa: BLE001
        return False


def _session(request: gr.Request | None) -> str:
    return getattr(request, "session_hash", None) or "local"


# ---------------------------------------------------------------------------- app

def create_ui(
    agent: Agent,
    rag_engine: RAGEngine,
    voice: VoiceEngine | None = None,
    *,
    store: ConversationStore | None = None,
    turns: TurnManager | None = None,
    tasks: TaskQueue | None = None,
    extensions: Extensions | None = None,
) -> gr.Blocks:
    """`store` and `turns` can be shared with the gateway API, so chats started from the phone
    show up here and vice versa."""
    config = agent.config
    hub = agent.hub
    store = store or ConversationStore(config.storage.conversations_db)
    turns = turns or TurnManager(agent, rag_engine, store, config)
    if tasks is None:
        tasks = TaskQueue(Path(config.storage.conversations_db).with_name("tasks.db"), turns)
        tasks.start()
    if extensions is None:
        extensions = Extensions(Path(config.storage.conversations_db).parent, agent.tool_registry, agent)
        extensions.start()
    doc_exts = [e for e in config.ingest.supported_extensions if e not in IMAGE_EXTS]
    threshold = config.agent.context_warning_threshold
    model_choices = [(f"{s.label} · {'cloud' if s.is_cloud else 'local'}", s.key) for s in hub.specs.values()]
    export_dir = Path(config.storage.conversations_db).parent / "exports"
    default_kv = kv_type(config.chat_models.default_kv_cache).key

    # Which chat each browser session is looking at. Followers stop painting the moment their
    # viewer opens another chat - the turn itself carries on in the background.
    viewing: dict[str, str] = {}
    viewing_lock = threading.Lock()

    def set_viewing(request, cid) -> None:
        with viewing_lock:
            viewing[_session(request)] = cid

    def is_viewing(request, cid) -> bool:
        with viewing_lock:
            return viewing.get(_session(request)) == cid

    def conv_items() -> list[dict]:
        busy = turns.running()
        return [{"id": c.id, "title": c.title, "updated": c.updated_at, "busy": c.id in busy} for c in store.list()]

    def title_of(cid: str | None) -> str:
        conv = store.get(cid) if cid else None
        return conv.title if conv else DEFAULT_TITLE

    def topbar(title: str, spec: ModelSpec, status: str | None = None) -> str:
        # Title, model and live status share one component: separate Gradio blocks in a row
        # collapse to zero width and swallow the title.
        pill = f"<div class='lm-status'><span class='lm-dot'></span>{html.escape(status)}…</div>" if status else ""
        where = "<span class='lm-badge lm-badge-cloud'>cloud</span>" if spec.is_cloud else "<span class='lm-badge'>local</span>"
        return (
            f"<div class='lm-topbar'><div class='lm-title'>{html.escape(title)}</div>"
            f"<div class='lm-model'>{html.escape(spec.label)} {where}</div><div class='lm-spacer'></div>{pill}</div>"
        )

    def footnote(spec: ModelSpec, kv: str | None = None) -> str:
        if not spec.is_cloud:
            detail = kv_type(kv).description
            return (
                f"<div class='lm-footnote'>Runs on this machine · KV cache: {html.escape(detail)} · attach PDFs, images, "
                "audio or LaTeX and they're indexed automatically</div>"
            )
        hint = credentials_hint()
        extra = f" <b>Not connected:</b> {html.escape(hint)}" if hint else ""
        return (
            f"<div class='lm-footnote lm-footnote-cloud'>{html.escape(spec.label)} runs in Anthropic's cloud: your messages, "
            f"retrieved document snippets and fetched pages are sent to Anthropic and billed to your account.{extra}</div>"
        )

    def kv_dropdown(spec: ModelSpec, kv: str | None):
        if spec.is_cloud:
            return gr.Dropdown(visible=False)
        choices = [(f"{t.key} · {_short(agent.context_window(spec.key, t.key))} context", t.key) for t in KV_CACHE_TYPES.values()]
        return gr.Dropdown(choices=choices, value=kv_type(kv).key, visible=True)

    def hud(ctx: dict | None, model_key: str | None) -> str:
        spec = hub.spec(model_key)
        pills = []
        gpu = gpu_stats()
        if gpu:
            pct = gpu.used_fraction
            level = " lm-hud-hot" if pct >= 0.92 else " lm-hud-warm" if pct >= 0.8 else ""
            pills.append(
                f"<span class='lm-hud-pill{level}' title='{html.escape(gpu.name)} - whole GPU, including other apps'>"
                f"<b>VRAM</b> {gpu.used_gb:.1f} / {gpu.total_gb:.0f} GB"
                f"<i class='lm-meter'><i style='width:{pct * 100:.0f}%'></i></i></span>"
            )
            if gpu.util_percent is not None:
                pills.append(f"<span class='lm-hud-pill'><b>GPU</b> {gpu.util_percent}%</span>")
        else:
            pills.append("<span class='lm-hud-pill'><b>GPU</b> n/a</span>")

        if ctx and ctx.get("window"):
            used = ctx["tokens"] / ctx["window"]
            left = max(0, ctx["window"] - ctx["tokens"])
            level = " lm-hud-hot" if used >= 0.95 else " lm-hud-warm" if used >= threshold else ""
            approx = "≈" if not ctx.get("exact", True) else ""
            pills.append(
                f"<span class='lm-hud-pill{level}' title='{html.escape(spec.label)} context window'>"
                f"<b>Context</b> {approx}{_short(ctx['tokens'])} / {_short(ctx['window'])} · {_short(left)} left"
                f"<i class='lm-meter'><i style='width:{min(100, used * 100):.0f}%'></i></i></span>"
            )
        else:
            pills.append("<span class='lm-hud-pill'><b>Context</b> —</span>")
        return f"<div class='lm-hud'>{''.join(pills)}</div>"

    def maybe_warn(cid: str | None, ctx: dict | None, spec: ModelSpec) -> None:
        """Toast once per chat and model when the context crosses the warning threshold."""
        if not cid or not ctx or not ctx.get("window"):
            return
        used = ctx["tokens"] / ctx["window"]
        warned = list(store.get_settings(cid).get("warned_for") or [])
        if used >= threshold and spec.key not in warned:
            gr.Warning(
                f"This chat has used {used:.0%} of {spec.label}'s context window "
                f"({_short(ctx['tokens'])} of {_short(ctx['window'])} tokens). Past this point the oldest messages "
                "drop out of what the model can see. Start a new chat, or pick a KV cache type with more room.",
                duration=12,
                title="Running out of context",
            )
            store.update_settings(cid, warned_for=warned + [spec.key])

    def kb_counts() -> tuple[int, int]:
        try:
            return len(rag_engine.list_sources()), rag_engine.count()
        except Exception:  # noqa: BLE001
            return 0, 0

    sections = rag_engine.sections

    def scope_choices() -> list[tuple[str, str]]:
        """'All knowledge', then each section (a private one also sees the shared ones)."""
        choices = [("All knowledge", "")]
        for section in sections.sections():
            label = section["name"] if section["shared"] else f"{section['name']} + shared"
            choices.append((label, section["name"]))
        return choices

    def section_choices() -> list[str]:
        return sections.names()

    def kb_mini_html() -> str:
        sources, chunks = kb_counts()
        return f"<div class='lm-kb-mini'>{sources} documents · {chunks} chunks indexed</div>"

    def nav(active: str):
        return [gr.Tabs(selected=active)] + [
            gr.Button(elem_classes=["lm-nav-active"] if view == active else []) for view in VIEWS
        ]

    with gr.Blocks(title="LocalMind", fill_height=True) as app:
        conv_id = gr.State(None)
        convs = gr.State([])
        web_on = gr.State(False)
        kb_on = gr.State(False)
        think_on = gr.State(False)
        # Per browser tab rather than per chat: it's about the device you're holding, and it stays
        # on as you move between chats.
        voice_on = gr.State(False)
        ctx_state = gr.State(None)

        hud_view = gr.HTML(elem_id="lm-hud")
        hud_timer = gr.Timer(HUD_INTERVAL)

        # ------------------------------------------------------------------ sidebar
        with gr.Sidebar(width=284, elem_id="lm-sidebar", open=True):
            with gr.Column(elem_id="lm-sidebar-inner"):
                gr.HTML("<div class='lm-brand'><div class='lm-mark'>LM</div><div class='lm-name'>LocalMind</div></div>")
                new_btn = gr.Button("New chat", elem_id="lm-new-chat", size="sm")
                chat_filter = gr.Textbox(
                    placeholder="Search chats",
                    show_label=False,
                    container=False,
                    elem_id="lm-chat-filter",
                    lines=1,
                    max_lines=1,
                )

                with gr.Column(elem_id="lm-conv-list"):

                    @gr.render(inputs=[convs, conv_id, chat_filter], triggers=[convs.change, conv_id.change, chat_filter.input])
                    def draw_conversations(items, active, query):
                        query = (query or "").strip().lower()
                        shown = [c for c in (items or []) if query in c["title"].lower()]
                        if not shown:
                            gr.HTML(f"<div class='lm-empty'>{'No matching chats' if query else 'No chats yet'}</div>")
                            return

                        today = dt.date.today()
                        current_group = None
                        for item in shown:
                            group = _group_label(item["updated"], today)
                            if group != current_group:
                                current_group = group
                                gr.HTML(f"<div class='lm-group-label'>{group}</div>")

                            classes = ["lm-conv-row"] + (["lm-active"] if item["id"] == active else []) + (["lm-busy"] if item.get("busy") else [])
                            with gr.Row(elem_classes=classes, equal_height=True):
                                pick = gr.Button(item["title"], size="sm", scale=1, min_width=0)
                                drop = gr.Button("✕", size="sm", scale=0, min_width=0, elem_classes=["lm-del"])

                            # Real functions, not lambdas: Gradio only injects gr.Request into
                            # annotated parameters, and followers need to know who is watching.
                            pick.click(opener(item["id"]), outputs=CHAT_OUT, show_progress="hidden").then(
                                remeasure, [conv_id, model_dd, think_on, kv_dd], [ctx_state, hud_view], show_progress="hidden"
                            ).then(follow, [conv_id, ctx_state], FOLLOW_OUT, show_progress="hidden", concurrency_limit=None, concurrency_id="follow")
                            drop.click(deleter(item["id"]), inputs=[conv_id], outputs=CHAT_OUT, show_progress="hidden")

                with gr.Column(elem_id="lm-nav"):
                    nav_chat = gr.Button("Chat", size="sm", elem_id="lm-nav-chat", elem_classes=["lm-nav-active"])
                    nav_kb = gr.Button("Knowledge base", size="sm", elem_id="lm-nav-kb")
                    nav_search = gr.Button("Search documents", size="sm", elem_id="lm-nav-search")
                    nav_tasks = gr.Button("Tasks", size="sm", elem_id="lm-nav-tasks")
                    nav_tools = gr.Button("Skills & tools", size="sm", elem_id="lm-nav-tools")
                    kb_mini = gr.HTML(kb_mini_html())

        # ------------------------------------------------------------------ views
        default_spec = hub.spec(None)
        with gr.Tabs(elem_id="lm-views", selected="chat") as views:
            with gr.Tab("Chat", id="chat"):
                with gr.Column(elem_id="lm-chat-view", elem_classes=["lm-view"]):
                    topbar_view = gr.HTML(topbar(DEFAULT_TITLE, default_spec), elem_id="lm-topbar")
                    chatbot = gr.Chatbot(
                        elem_id="lm-chatbox",
                        # A starting point only: the stylesheet makes this flex to whatever the
                        # composer card and footnote leave over, which varies with the toolbar.
                        height="calc(100vh - 330px)",
                        show_label=False,
                        container=False,
                        placeholder=HERO,
                        examples=STARTERS,
                        buttons=["copy"],
                        group_consecutive_messages=False,
                        # Off: the page script follows new tokens only while you're at the bottom,
                        # so you can scroll back through an answer as it streams.
                        autoscroll=False,
                    )
                    with gr.Group(elem_id="lm-composer-card"):
                        composer = gr.MultimodalTextbox(
                            elem_id="lm-composer",
                            placeholder="Message LocalMind…",
                            show_label=False,
                            container=False,
                            file_types=sorted(IMAGE_EXTS) + doc_exts,
                            file_count="multiple",
                            sources=["upload"],
                            submit_btn=True,
                            stop_btn=False,  # swapped in while a reply is streaming
                            autofocus=True,
                            max_lines=12,
                        )
                        with gr.Row(elem_id="lm-toolbar"):
                            model_dd = gr.Dropdown(
                                choices=model_choices,
                                value=hub.default_key,
                                show_label=False,
                                container=False,
                                filterable=False,
                                scale=0,
                                min_width=0,
                                elem_id="lm-model-picker",
                            )
                            web_btn = gr.Button("Web search", size="sm", scale=0, min_width=0, elem_id="lm-chip-web", elem_classes=_chip(False))
                            kb_btn = gr.Button("Knowledge base", size="sm", scale=0, min_width=0, elem_id="lm-chip-kb", elem_classes=_chip(False))
                            think_btn = gr.Button("Thinking", size="sm", scale=0, min_width=0, elem_id="lm-chip-think", elem_classes=_chip(False))
                            voice_btn = gr.Button("Voice", size="sm", scale=0, min_width=0, elem_id="lm-chip-voice", elem_classes=_chip(False))
                            kv_dd = gr.Dropdown(
                                choices=[(t.key, t.key) for t in KV_CACHE_TYPES.values()],
                                value=default_kv,
                                show_label=False,
                                container=False,
                                filterable=False,
                                scale=0,
                                min_width=0,
                                elem_id="lm-kv-picker",
                            )
                            scope_dd = gr.Dropdown(
                                choices=scope_choices(),
                                value="",
                                show_label=False,
                                container=False,
                                filterable=False,
                                scale=0,
                                min_width=0,
                                elem_id="lm-scope-picker",
                            )
                            # No spacer element: Gradio gives blocks a minimum width, which pushed
                            # this onto a third toolbar row. `margin-left: auto` does the same job.
                            export_btn = gr.Button("PDF", size="sm", scale=0, min_width=0, elem_id="lm-export", elem_classes=["lm-chip"])
                    export_file = gr.DownloadButton("download", elem_id="lm-export-file", visible=True)
                    footnote_view = gr.HTML(footnote(default_spec, default_kv))

            with gr.Tab("Knowledge", id="kb"):
                with gr.Column(elem_classes=["lm-view"]):
                    kb_head = gr.HTML()
                    with gr.Row(equal_height=False):
                        with gr.Column(scale=5, elem_classes=["lm-card"]):
                            gr.HTML("<div class='lm-card-title'>Add documents</div>")
                            file_upload = gr.File(
                                show_label=False,
                                file_count="multiple",
                                file_types=config.ingest.supported_extensions,
                                height=190,
                            )
                            upload_section = gr.Dropdown(
                                choices=section_choices(), value=DEFAULT_SECTION, label="Add to section",
                                filterable=False, elem_id="lm-upload-section",
                            )
                            upload_btn = gr.Button("Index documents", variant="primary")
                            upload_status = gr.Markdown()
                            gr.HTML("<div class='lm-card-title' style='margin-top:14px'>Sections</div>")
                            sections_view = gr.HTML()
                            with gr.Row(equal_height=True):
                                new_section_name = gr.Textbox(placeholder="New section, e.g. Barclays", show_label=False, container=False, scale=3)
                                new_section_shared = gr.Checkbox(label="Shared with every chat", value=False, scale=2)
                            create_section_btn = gr.Button("Create section", size="sm")
                            with gr.Row(equal_height=True):
                                manage_section = gr.Dropdown(choices=section_choices(), value=DEFAULT_SECTION, show_label=False, container=False, filterable=False, scale=3)
                                share_section_btn = gr.Button("Share / unshare", size="sm", scale=2)
                                delete_section_btn = gr.Button("Delete", size="sm", variant="stop", scale=1)
                        with gr.Column(scale=7, elem_classes=["lm-card"]):
                            gr.HTML("<div class='lm-card-title'>Indexed documents</div>")
                            sources_table = gr.Dataframe(
                                headers=["Document", "Section", "Chunks"],
                                datatype=["str", "str", "number"],
                                interactive=False,
                                wrap=True,
                                max_height=340,
                                column_widths=["58%", "27%", "15%"],
                                elem_id="lm-sources",
                            )
                            selected_source = gr.State(None)
                            with gr.Row(equal_height=True):
                                move_section = gr.Dropdown(choices=section_choices(), value=None, show_label=False, container=False, filterable=False, interactive=False, scale=3)
                                move_btn = gr.Button("Move to section", size="sm", interactive=False, scale=2)
                            delete_btn = gr.Button(NO_SELECTION, variant="stop", interactive=False, size="sm")

            with gr.Tab("Search", id="search"):
                with gr.Column(elem_classes=["lm-view"]):
                    gr.HTML(
                        "<div class='lm-page-head'><h2>Search documents</h2>"
                        "<p>See exactly what the retriever hands the model — the fastest way to debug a bad answer.</p></div>"
                    )
                    with gr.Row(equal_height=True, elem_id="lm-search-row"):
                        search_input = gr.Textbox(
                            placeholder="e.g. machine learning internship",
                            show_label=False,
                            scale=8,
                            container=False,
                            elem_id="lm-search-input",
                        )
                        top_k = gr.Slider(1, 25, value=6, step=1, label="Results", scale=3)
                        search_btn = gr.Button("Search", variant="primary", scale=1, min_width=90)
                    search_results = gr.HTML()

            with gr.Tab("Tasks", id="tasks"):
                with gr.Column(elem_classes=["lm-view"]):
                    gr.HTML(
                        "<div class='lm-page-head'><h2>Task queue</h2>"
                        "<p>One set of instructions, several items: each item becomes its own fresh chat, "
                        "and they run one after another. The PC stays on until the queue is empty.</p></div>"
                    )
                    with gr.Row(equal_height=False):
                        with gr.Column(scale=6, elem_classes=["lm-card"]):
                            gr.HTML("<div class='lm-card-title'>New batch</div>")
                            task_name = gr.Textbox(label="Name", placeholder="Graduate applications")
                            task_instructions = gr.Textbox(label="Instructions for every task", lines=5, placeholder=TASK_INSTRUCTIONS_HINT)
                            task_items = gr.Textbox(
                                label="Items: one per task, separated by a line of ---", lines=8,
                                placeholder="Barclays, Graduate Analyst\n(job description)\n---\nBlackRock, Associate\n(job description)",
                            )
                            task_files = gr.File(label="or attach one file per task", file_count="multiple", file_types=[".txt", ".md", ".pdf", ".tex"], height=120)
                            with gr.Row():
                                task_model = gr.Dropdown(choices=model_choices, value=hub.default_key, label="Model", filterable=False)
                                task_scope = gr.Dropdown(choices=scope_choices(), value="", label="Knowledge it can see", filterable=False)
                            with gr.Row():
                                task_kb = gr.Checkbox(label="Use knowledge base", value=True)
                                task_web = gr.Checkbox(label="Web search", value=False)
                                task_think = gr.Checkbox(label="Thinking", value=False)
                            queue_btn = gr.Button("Queue tasks", variant="primary")
                            queue_status = gr.Markdown()
                        with gr.Column(scale=6, elem_classes=["lm-card"]):
                            gr.HTML("<div class='lm-card-title'>Queue</div>")
                            queue_view = gr.HTML()
                            with gr.Row():
                                cancel_tasks_btn = gr.Button("Cancel waiting tasks", size="sm", variant="stop")
                                retry_tasks_btn = gr.Button("Retry failed or cancelled", size="sm")

            with gr.Tab("Skills & tools", id="tools"):
                with gr.Column(elem_classes=["lm-view"]):
                    gr.HTML(
                        "<div class='lm-page-head'><h2>Skills &amp; tools</h2>"
                        "<p>Skills teach the model a task; MCP servers give it other programs' tools. The model "
                        "can ask for new ones, but only you can approve them.</p></div>"
                    )
                    with gr.Row(equal_height=False):
                        with gr.Column(scale=6, elem_classes=["lm-card"]):
                            gr.HTML("<div class='lm-card-title'>Waiting for your approval</div>")
                            requests_view = gr.HTML()
                            with gr.Row(equal_height=True):
                                request_pick = gr.Dropdown(choices=[], show_label=False, container=False, filterable=False, scale=3)
                                approve_btn = gr.Button("Approve", size="sm", variant="primary", scale=1, min_width=0)
                                deny_btn = gr.Button("Deny", size="sm", scale=1, min_width=0)
                            gr.HTML("<div class='lm-card-title' style='margin-top:14px'>Skills</div>")
                            skills_view = gr.HTML()
                            skill_url = gr.Textbox(show_label=False, placeholder="https://github.com/anthropics/skills/tree/main/skills/pdf")
                            install_skill_btn = gr.Button("Install skill", size="sm")
                            with gr.Row(equal_height=True):
                                skill_pick = gr.Dropdown(choices=[], show_label=False, container=False, filterable=False, scale=3)
                                remove_skill_btn = gr.Button("Remove", size="sm", variant="stop", scale=1)
                        with gr.Column(scale=6, elem_classes=["lm-card"]):
                            gr.HTML("<div class='lm-card-title'>MCP servers</div>")
                            mcp_view = gr.HTML()
                            mcp_name = gr.Textbox(show_label=False, placeholder="Name, e.g. files")
                            mcp_target = gr.Textbox(show_label=False, placeholder="Command (npx -y @modelcontextprotocol/server-filesystem C:/Notes) or URL")
                            add_mcp_btn = gr.Button("Add server", size="sm")
                            with gr.Row(equal_height=True):
                                mcp_pick = gr.Dropdown(choices=[], show_label=False, container=False, filterable=False, scale=3)
                                remove_mcp_btn = gr.Button("Remove", size="sm", variant="stop", scale=1)
                            tools_status = gr.Markdown()
            tasks_timer = gr.Timer(3.0)

        NAV_OUT = [views, nav_chat, nav_kb, nav_search, nav_tasks, nav_tools]
        SETTINGS_OUT = [model_dd, web_on, kb_on, think_on, web_btn, kb_btn, think_btn, kv_dd, ctx_state, footnote_view, scope_dd]
        CHAT_OUT = [chatbot, conv_id, convs, topbar_view, composer, *SETTINGS_OUT, *NAV_OUT]
        FOLLOW_OUT = [chatbot, topbar_view, composer, convs, ctx_state, hud_view]

        # ------------------------------------------------------------------ per-chat settings
        def settings_updates(cid: str | None) -> dict:
            saved = store.get_settings(cid)
            spec = hub.spec(saved.get("model"))
            thinking = spec.thinking == "always" or (bool(saved.get("thinking")) and spec.can_toggle_thinking)
            web, kb = bool(saved.get("web")), bool(saved.get("kb"))
            kv = kv_type(saved.get("kv") or spec.kv_cache or default_kv).key
            return {
                model_dd: gr.Dropdown(value=spec.key),
                web_on: web,
                kb_on: kb,
                think_on: thinking,
                web_btn: gr.Button(elem_classes=_chip(web)),
                kb_btn: gr.Button(elem_classes=_chip(kb)),
                think_btn: _thinking_button(spec, thinking),
                kv_dd: kv_dropdown(spec, kv),
                ctx_state: saved.get("context"),
                footnote_view: footnote(spec, kv),
                scope_dd: gr.Dropdown(choices=scope_choices(), value=saved.get("scope") if saved.get("scope") in sections.names() else ""),
            }

        def chat_view(cid: str, display: list, request, items: list | None = None) -> dict:
            set_viewing(request, cid)
            spec = hub.spec(store.get_settings(cid).get("model"))
            turn = turns.get(cid)
            running = bool(turn and not turn.done)
            if running:
                display = turn.snapshot()[1]
            return {
                chatbot: display,
                conv_id: cid,
                convs: items if items is not None else conv_items(),
                topbar_view: topbar(title_of(cid), spec, turn.snapshot()[2] if running else None),
                composer: _composer_busy() if running else _composer_ready(),
                **settings_updates(cid),
                **dict(zip(NAV_OUT, nav("chat"))),
            }

        def open_conversation(cid: str, request: gr.Request) -> dict:
            return chat_view(cid, store.load(cid)[0], request)

        def opener(cid: str):
            def handler(request: gr.Request):
                return open_conversation(cid, request)
            return handler

        def deleter(cid: str):
            def handler(current, request: gr.Request):
                return delete_conversation(cid, current, request)
            return handler

        def new_conversation(items, model_key, thinking, kv, request: gr.Request):
            # Reuse an untouched chat rather than piling up empties; keep the chosen model and cache.
            reusable = next((c["id"] for c in items or [] if not c.get("busy") and store.is_empty(c["id"])), None)
            cid = reusable or store.create()
            kv = kv or kv_type(hub.spec(model_key).kv_cache or default_kv).key
            store.update_settings(cid, model=model_key, thinking=thinking, kv=kv, web=False, kb=False, scope="", context=None, warned_for=[])
            return chat_view(cid, [], request)

        def delete_conversation(cid: str, current: str | None, request: gr.Request) -> dict:
            turns.cancel(cid)
            store.delete(cid)
            remaining = conv_items()
            if cid != current and any(c["id"] == current for c in remaining):
                # Deleting some other chat shouldn't pull the user out of the one they're reading.
                return {convs: remaining}
            if not remaining:
                return chat_view(store.create(), [], request)
            target = remaining[0]["id"]
            return chat_view(target, store.load(target)[0], request, remaining)

        def bootstrap(request: gr.Request):
            items = conv_items()
            cid = items[0]["id"] if items else store.create()
            return {**chat_view(cid, store.load(cid)[0], request), kb_mini: kb_mini_html()}

        def remeasure(cid, model_key, thinking, kv):
            if not cid:
                return gr.skip(), gr.skip()
            spec = hub.spec(model_key)
            transcript = normalize_transcript(store.load(cid)[1])
            usage = agent.measure_context(model_key, thinking, kv, transcript=transcript).as_dict()
            maybe_warn(cid, usage, spec)
            store.update_settings(cid, context=usage)
            return usage, hud(usage, model_key)

        def on_model_change(model_key, cid, thinking, kv):
            spec = hub.spec(model_key)
            thinking = spec.thinking == "always" or (thinking and spec.can_toggle_thinking)
            # Each model has its own best cache: fp8 pays off on Qwen, bf16 already fits Gemma's full context.
            kv = kv_type(spec.kv_cache or default_kv).key
            store.update_settings(cid, model=spec.key, thinking=thinking, kv=kv)
            if spec.is_cloud and credentials_hint():
                gr.Warning(f"{spec.label} isn't connected yet. {credentials_hint()}", duration=10)
            return {
                think_on: thinking,
                think_btn: _thinking_button(spec, thinking),
                kv_dd: kv_dropdown(spec, kv),
                footnote_view: footnote(spec, kv),
                topbar_view: topbar(title_of(cid), spec),
            }

        def on_kv_change(kv, cid, model_key):
            spec = hub.spec(model_key)
            kind = kv_type(kv)
            store.update_settings(cid, kv=kind.key)
            if kind.slow:
                gr.Info(f"{kind.key}: {kind.description}", duration=8)
            return footnote(spec, kind.key)

        def toggle(flag: str):
            def flip(current, cid):
                value = not current
                store.update_settings(cid, **{flag: value})
                return value, gr.Button(elem_classes=_chip(value))
            return flip

        def toggle_voice(current):
            if not current and (voice is None or not voice.tts_installed()):
                gr.Warning("Voice needs the kokoro-onnx package for speech output:  pip install kokoro-onnx")
                return False, gr.Button(elem_classes=_chip(False))
            value = not current
            if value:
                voice.warm()  # load Whisper and Kokoro now, while you're still deciding what to say
            return value, gr.Button(elem_classes=_chip(value))

        def toggle_thinking(current, model_key, cid):
            spec = hub.spec(model_key)
            if not spec.can_toggle_thinking:
                return current, _thinking_button(spec, current)
            value = not current
            if value and spec.thinking == "variant" and not _variant_cached(spec.thinking_model):
                gr.Info(f"{spec.label} thinks with a separate checkpoint ({spec.thinking_model}). The first message downloads it (~16 GB).", duration=10)
            store.update_settings(cid, thinking=value)
            return value, _thinking_button(spec, value)

        # ------------------------------------------------------------------ chat turns
        def start_turn(value, history, cid, model_key, web, kb, thinking, kv, spoken, scope, request: gr.Request):
            value = value or {}
            text = (value.get("text") or "").strip()
            files = [_file_path(f) for f in (value.get("files") or [])]
            if not text and not files:
                return {composer: gr.skip()}
            try:
                cid, history, turn, title = turns.submit(
                    cid=cid, text=text, files=files, model_key=model_key, web=web, kb=kb,
                    thinking=thinking, kv=kv, voice=bool(spoken), scope=scope or "", history=history or [],
                )
            except TurnBusy as e:
                set_viewing(request, cid)
                gr.Warning(str(e))
                return {composer: _composer_busy()}
            set_viewing(request, cid)
            return {
                composer: _composer_busy(),
                chatbot: history,
                conv_id: cid,
                convs: conv_items(),
                topbar_view: topbar(title, hub.spec(model_key), turn.snapshot()[2]),
            }

        def follow(cid, ctx, request: gr.Request):
            """Stream a turn's progress to this viewer until it finishes or they look elsewhere."""
            turn = turns.get(cid)
            if turn is None:
                yield {chatbot: gr.skip()}
                return
            spec = hub.spec(turn.request.model_key)
            title = title_of(cid)
            version, last_paint = -1, 0.0
            last_ctx = ctx
            while True:
                turn.wait(version, timeout=0.5)
                if not is_viewing(request, cid):
                    return  # they opened another chat; the turn keeps running
                snap_version, history, status, turn_ctx, done = turn.snapshot()
                if snap_version == version and not done:
                    continue
                wait = STREAM_INTERVAL - (time.monotonic() - last_paint)
                if wait > 0 and not done:
                    time.sleep(wait)
                    continue
                version, last_paint = snap_version, time.monotonic()

                frame = {chatbot: history, topbar_view: topbar(title, spec, None if done else status)}
                if turn_ctx and turn_ctx != last_ctx:
                    last_ctx = turn_ctx
                    maybe_warn(cid, turn_ctx, spec)
                    frame[ctx_state] = turn_ctx
                    frame[hud_view] = hud(turn_ctx, spec.key)
                if done:
                    frame[composer] = _composer_ready()
                    frame[convs] = conv_items()
                if not is_viewing(request, cid):
                    return
                yield frame
                if done:
                    return

        def start_starter(history, cid, model_key, web, kb, thinking, kv, spoken, scope, evt: gr.SelectData, request: gr.Request):
            return start_turn({"text": evt.value.get("text", ""), "files": []}, history, cid, model_key, web, kb, thinking, kv, spoken, scope, request)

        def stop_turn(cid):
            turns.cancel(cid)

        def export_chat(cid, model_key):
            turn = turns.get(cid)
            history = turn.snapshot()[1] if turn and not turn.done else store.load(cid)[0] if cid else []
            if not history:
                gr.Warning("There's nothing in this chat to export yet.")
                return gr.skip()
            title = title_of(cid)
            path = export_pdf(export_dir / safe_filename(title), title, history, hub.spec(model_key).label)
            return gr.DownloadButton(value=str(path))

        turn_inputs = [conv_id, model_dd, web_on, kb_on, think_on, kv_dd, voice_on, scope_dd]
        start_outputs = [composer, chatbot, conv_id, convs, topbar_view]
        composer.submit(
            start_turn, [composer, chatbot, *turn_inputs], start_outputs, show_progress="hidden",
        ).then(follow, [conv_id, ctx_state], FOLLOW_OUT, show_progress="hidden", concurrency_limit=None, concurrency_id="follow")
        chatbot.example_select(
            start_starter, [chatbot, *turn_inputs], start_outputs, show_progress="hidden",
        ).then(follow, [conv_id, ctx_state], FOLLOW_OUT, show_progress="hidden", concurrency_limit=None, concurrency_id="follow")
        composer.stop(stop_turn, [conv_id], None, queue=False)

        new_btn.click(
            new_conversation, [convs, model_dd, think_on, kv_dd], CHAT_OUT, show_progress="hidden",
        ).then(remeasure, [conv_id, model_dd, think_on, kv_dd], [ctx_state, hud_view], show_progress="hidden")

        model_dd.select(  # .input fires more than once per pick; .select fires exactly once
            on_model_change, [model_dd, conv_id, think_on, kv_dd], [think_on, think_btn, kv_dd, footnote_view, topbar_view], show_progress="hidden"
        ).then(remeasure, [conv_id, model_dd, think_on, kv_dd], [ctx_state, hud_view], show_progress="hidden")
        def on_scope_change(scope, cid):
            store.update_settings(cid, scope=scope or "")
            if scope:
                gr.Info(f"This chat's knowledge searches now see: {sections.describe_scope(scope)}.", duration=6)

        scope_dd.select(on_scope_change, [scope_dd, conv_id], None, show_progress="hidden", queue=False)
        kv_dd.select(on_kv_change, [kv_dd, conv_id, model_dd], [footnote_view], show_progress="hidden").then(
            remeasure, [conv_id, model_dd, think_on, kv_dd], [ctx_state, hud_view], show_progress="hidden"
        )
        web_btn.click(toggle("web"), [web_on, conv_id], [web_on, web_btn], show_progress="hidden", queue=False)
        kb_btn.click(toggle("kb"), [kb_on, conv_id], [kb_on, kb_btn], show_progress="hidden", queue=False)
        think_btn.click(
            toggle_thinking, [think_on, model_dd, conv_id], [think_on, think_btn], show_progress="hidden", queue=False
        ).then(remeasure, [conv_id, model_dd, think_on, kv_dd], [ctx_state, hud_view], show_progress="hidden")

        # The page script runs the conversation loop (listen, send, speak); this tells it the verdict.
        # It reads the chip rather than voice_on: gr.State stays on the server, so JS would get null.
        voice_btn.click(toggle_voice, [voice_on], [voice_on, voice_btn], show_progress="hidden", queue=False).then(
            None, None, None,
            js="() => setTimeout(() => window.lmVoice && window.lmVoice.set("
               "!!document.querySelector('#lm-chip-voice.lm-chip-on')), 30)",
        )

        export_btn.click(export_chat, [conv_id, model_dd], [export_file], show_progress="hidden").then(
            None, None, None,
            js="() => setTimeout(() => document.querySelector('#lm-export-file')?.click(), 120)",
        )

        def tick(ctx, model_key, items):
            # Refresh the sidebar only when a background turn starts or finishes, so its busy dots
            # stay right without re-rendering the list every two seconds.
            running = turns.running()
            shown = {c["id"] for c in items or [] if c.get("busy")}
            return hud(ctx, model_key), (conv_items() if running != shown else gr.skip())

        hud_timer.tick(tick, [ctx_state, model_dd, convs], [hud_view, convs], show_progress="hidden", concurrency_limit=None, concurrency_id="hud")

        # ------------------------------------------------------------------ navigation
        def refresh_kb():
            return kb_head_html(), source_rows(), kb_mini_html()

        SECTIONS_OUT = [sections_view, upload_section, move_section, manage_section, scope_dd]

        nav_chat.click(lambda: nav("chat"), outputs=NAV_OUT, show_progress="hidden", queue=False)
        nav_kb.click(lambda: nav("kb"), outputs=NAV_OUT, show_progress="hidden", queue=False).then(
            refresh_kb, outputs=[kb_head, sources_table, kb_mini], show_progress="hidden"
        ).then(lambda keep: refresh_sections(keep), [upload_section], SECTIONS_OUT, show_progress="hidden")
        nav_search.click(lambda: nav("search"), outputs=NAV_OUT, show_progress="hidden", queue=False)

        # ------------------------------------------------------------------ knowledge base
        def source_rows():
            import pandas as pd

            try:
                table = rag_engine.db.open_table(rag_engine.TABLE_NAME)
                if table.count_rows() == 0:
                    return pd.DataFrame(columns=["Document", "Section", "Chunks"])
                counts = table.to_arrow().column("source").to_pandas().value_counts().sort_index()
                return pd.DataFrame({
                    "Document": counts.index,
                    "Section": [sections.section_of(name) for name in counts.index],
                    "Chunks": counts.values,
                })
            except Exception as e:  # noqa: BLE001
                logger.warning("Could not read sources: %s", e)
                return pd.DataFrame(columns=["Document", "Section", "Chunks"])

        def kb_head_html() -> str:
            sources, chunks = kb_counts()
            return (
                "<div class='lm-page-head'><h2>Knowledge base</h2>"
                "<p>Everything the assistant can cite. Files you attach in chat land here too.</p>"
                "<div class='lm-stats'>"
                f"<span class='lm-stat'><b>{sources}</b> documents</span>"
                f"<span class='lm-stat'><b>{chunks}</b> chunks</span></div></div>"
            )

        def sections_html() -> str:
            rows = []
            for section in sections.sections():
                badge = "<span class='lm-badge'>shared</span>" if section["shared"] else "<span class='lm-badge lm-badge-cloud'>private</span>"
                count = section["documents"]
                rows.append(f"<div class='lm-section-row'><b>{html.escape(section['name'])}</b> {badge} "
                            f"<span class='lm-muted'>{count} document{'s' if count != 1 else ''}</span></div>")
            return ("<div class='lm-sections'>" + "".join(rows) + "<p class='lm-muted' style='margin:6px 0 0'>"
                    "Shared sections are searchable from every chat; a private one only from chats scoped to it "
                    "(pick the scope in the chat toolbar).</p></div>")

        def refresh_sections(keep_upload=None, keep_manage=None):
            names = section_choices()
            return (
                sections_html(),
                gr.Dropdown(choices=names, value=keep_upload if keep_upload in names else DEFAULT_SECTION),
                gr.Dropdown(choices=names),
                gr.Dropdown(choices=names, value=keep_manage if keep_manage in names else DEFAULT_SECTION),
                gr.Dropdown(choices=scope_choices()),
            )

        def create_section(name, shared, upload_to):
            clean = " ".join((name or "").split())
            try:
                sections.create(clean, shared)
            except SectionError as e:
                gr.Warning(str(e))
                return (gr.skip(),) * 6
            gr.Info(f"Created {'shared' if shared else 'private'} section \u201c{clean}\u201d.")
            return (*refresh_sections(upload_to, clean), "")

        def toggle_section_shared(name, upload_to):
            try:
                sections.set_shared(name, not sections.is_shared(name))
            except SectionError as e:
                gr.Warning(str(e))
            return refresh_sections(upload_to, name)

        def delete_section(name, upload_to):
            try:
                moved = sections.delete(name)
                gr.Info(f"Deleted {name}. {moved} document{'s' if moved != 1 else ''} moved to {DEFAULT_SECTION}.")
            except SectionError as e:
                gr.Warning(str(e))
            return (*refresh_sections(upload_to), source_rows())

        def move_source(name, section, upload_to):
            if not name or not section:
                return (gr.skip(),) * 6
            try:
                sections.assign(name, section)
            except SectionError as e:
                gr.Warning(str(e))
            return (*refresh_sections(upload_to), source_rows())

        def handle_upload(files, section=None, progress=gr.Progress()):
            if not files:
                return "Choose some files first.", gr.skip(), gr.skip(), gr.skip(), gr.skip()

            from localmind.ingest.pipeline import IngestPipeline

            pipeline = IngestPipeline(config, agent.model_manager)
            lines = []
            for item in progress.tqdm(files, desc="Indexing"):
                path = _file_path(item)
                name = getattr(item, "orig_name", None) or path.name
                try:
                    count = rag_engine.add_chunks(pipeline.process_to_chunks(path, source_name=name))
                    sections.assign(name, section or DEFAULT_SECTION)
                    lines.append(f"✅ **{name}** · {count} chunks · {section or DEFAULT_SECTION}")
                except Exception as e:  # noqa: BLE001
                    logger.exception("Ingest failed for %s", path)
                    lines.append(f"❌ **{name}** · {html.escape(str(e))}")
            return ("\n\n".join(lines), *refresh_kb(), None)

        def select_source(evt: gr.SelectData):
            row = getattr(evt, "row_value", None)
            name = row[0] if row else evt.value
            if not name:
                return None, gr.Button(NO_SELECTION, interactive=False), gr.Dropdown(interactive=False), gr.Button(interactive=False)
            return (
                name,
                gr.Button(f"Remove “{name}”", interactive=True),
                gr.Dropdown(choices=section_choices(), value=sections.section_of(name), interactive=True),
                gr.Button(interactive=True),
            )

        def delete_source(name):
            if not name:
                return gr.skip(), gr.skip(), gr.skip(), gr.skip(), None, gr.skip()
            try:
                removed = rag_engine.delete_source(name)
                note = f"🗑️ Removed **{name}** · {removed} chunks"
            except Exception as e:  # noqa: BLE001
                note = f"❌ {html.escape(str(e))}"
            return (note, *refresh_kb(), None, gr.Button(NO_SELECTION, interactive=False))

        upload_btn.click(
            handle_upload, [file_upload, upload_section], [upload_status, kb_head, sources_table, kb_mini, file_upload],
            show_progress="minimal",
        ).then(lambda keep: refresh_sections(keep), [upload_section], SECTIONS_OUT, show_progress="hidden")
        sources_table.select(select_source, None, [selected_source, delete_btn, move_section, move_btn], show_progress="hidden")
        create_section_btn.click(create_section, [new_section_name, new_section_shared, upload_section], [*SECTIONS_OUT, new_section_name], show_progress="hidden")
        share_section_btn.click(toggle_section_shared, [manage_section, upload_section], SECTIONS_OUT, show_progress="hidden")
        delete_section_btn.click(delete_section, [manage_section, upload_section], [*SECTIONS_OUT, sources_table], show_progress="hidden")
        move_btn.click(move_source, [selected_source, move_section, upload_section], [*SECTIONS_OUT, sources_table], show_progress="hidden")
        delete_btn.click(
            delete_source, [selected_source], [upload_status, kb_head, sources_table, kb_mini, selected_source, delete_btn],
            show_progress="hidden",
        )

        # ------------------------------------------------------------------ tasks
        def queue_html() -> str:
            batches = tasks.batches(limit=12)
            if not batches:
                return "<p class='lm-muted'>Nothing queued yet.</p>"
            parts = []
            for batch in batches:
                rows = []
                for task in batch["tasks"]:
                    icon = STATE_ICONS.get(task["state"], "")
                    took = ""
                    if task["started"] and task["finished"]:
                        took = f" · {int(task['finished'] - task['started'])}s"
                    elif task["started"]:
                        took = f" · {int(time.time() - task['started'])}s so far"
                    error = f"<div class='lm-task-error'>{html.escape(task['error'])}</div>" if task["error"] else ""
                    rows.append(f"<div class='lm-task'><span>{icon}</span><span class='lm-task-title'>{html.escape(task['title'])}</span>"
                                f"<span class='lm-muted'>{task['state']}{took}</span></div>{error}")
                done = sum(t["state"] == "done" for t in batch["tasks"])
                parts.append(f"<div class='lm-batch'><div class='lm-batch-head'><b>{html.escape(batch['name'])}</b>"
                             f"<span class='lm-muted'>{done}/{len(batch['tasks'])} done</span></div>{''.join(rows)}</div>")
            return "".join(parts) + "<p class='lm-muted' style='margin-top:8px'>Finished tasks appear as chats in the sidebar, named after the batch.</p>"

        def queue_tasks(name, instructions, items_text, files, model_key, scope, kb, web, thinking):
            items = split_items(items_text)
            for item in files or []:
                path = _file_path(item)
                try:
                    items.append(item_from_file(path, getattr(item, "orig_name", None) or path.name))
                except Exception as e:  # noqa: BLE001
                    gr.Warning(f"Couldn't read {path.name}: {e}")
            spec = hub.spec(model_key)
            options = {"model": spec.key, "scope": scope or "", "kb": bool(kb), "web": bool(web), "thinking": bool(thinking),
                       "kv": kv_type(spec.kv_cache or default_kv).key}
            try:
                batch = tasks.add_batch(name, instructions or "", items, options)
            except ValueError as e:
                return str(e), gr.skip(), gr.skip(), gr.skip(), gr.skip()
            count = len(batch["tasks"])
            return (f"Queued **{count}** task{'s' if count != 1 else ''} in **{html.escape(batch['name'])}**. "
                    "They run one at a time; each opens its own chat.", queue_html(), "", None, sidebar_labels()[0])

        def sidebar_labels():
            waiting = tasks.summary()
            count = waiting["waiting"] + waiting["running"]
            pending = len(extensions.requests.pending())
            return (
                gr.Button(value=f"Tasks ({count})" if count else "Tasks"),
                gr.Button(value=f"Skills & tools ({pending} to approve)" if pending else "Skills & tools"),
            )

        def cancel_tasks():
            cancelled = tasks.cancel()
            return f"Cancelled {cancelled} task{'s' if cancelled != 1 else ''}.", queue_html()

        def retry_tasks():
            again = tasks.retry_failed()
            return f"Queued {again} task{'s' if again != 1 else ''} again.", queue_html()

        # ------------------------------------------------------------------ skills & tools
        def tools_refresh():
            pending = extensions.requests.pending()
            if pending:
                cards = []
                for r in pending:
                    what = "Skill" if r["kind"] == "skill" else "MCP server"
                    cards.append(f"<div class='lm-request'><b>{what}</b> <code>{html.escape(r['source'])}</code>"
                                 f"<div>{html.escape(r['reason'])}</div></div>")
                requests_html = "".join(cards)
            else:
                requests_html = "<p class='lm-muted'>Nothing waiting. When the model asks for a skill or server, it appears here (and on your phone).</p>"
            skills = extensions.skills.list()
            skills_html = "".join(
                f"<div class='lm-request'><b>{html.escape(s.name)}</b><div class='lm-muted'>{html.escape(s.description[:220])}</div></div>"
                for s in skills
            ) or "<p class='lm-muted'>No skills installed.</p>"
            servers = extensions.mcp.describe()
            mcp_html = "".join(
                f"<div class='lm-request'><b>{html.escape(m['name'])}</b> <span class='lm-badge'>{m['state']}</span>"
                f"<div class='lm-muted'><code>{html.escape(m['target'][:120])}</code> · {len(m['tools'])} tools"
                f"{' · ' + html.escape(m['error']) if m.get('error') else ''}</div></div>"
                for m in servers
            ) or "<p class='lm-muted'>No MCP servers connected.</p>"
            request_choices = [(f"{r['kind']}: {r['source'][:60]}", r["id"]) for r in pending]
            return (
                requests_html,
                gr.Dropdown(choices=request_choices, value=request_choices[0][1] if request_choices else None),
                skills_html,
                gr.Dropdown(choices=[s.name for s in skills], value=skills[0].name if skills else None),
                mcp_html,
                gr.Dropdown(choices=[m["name"] for m in servers], value=servers[0]["name"] if servers else None),
            )

        def decide(request_id, approve):
            if not request_id:
                return ("Pick a request first.", *tools_refresh())
            try:
                result = extensions.requests.decide(request_id, approve)
            except KeyError:
                return ("That request has gone.", *tools_refresh())
            note = result.get("result") or ("Denied." if not approve else "Done.")
            return (note, *tools_refresh())

        def install_skill(url):
            try:
                skill = extensions.skills.install(url or "")
                note = f"Installed **{html.escape(skill.name)}**."
            except Exception as e:  # noqa: BLE001
                note = f"Couldn't install: {html.escape(str(e))}"
            return (note, *tools_refresh(), "")

        def remove_skill(name):
            note = f"Removed {name}." if name and extensions.skills.remove(name) else "Pick a skill first."
            return (note, *tools_refresh())

        def add_mcp(name, target):
            try:
                status = extensions.mcp.add(name or "", McpHub.spec_from(target or ""))
                if status.get("state") == "connected":
                    note = f"Connected **{html.escape(name)}** with {len(status['tools'])} tools."
                else:
                    note = f"Added {html.escape(name)}, but it didn't connect: {html.escape(str(status.get('error')))}"
            except Exception as e:  # noqa: BLE001
                note = f"Couldn't add it: {html.escape(str(e))}"
            return (note, *tools_refresh(), "", "")

        def remove_mcp(name):
            note = f"Removed {name}." if name and extensions.mcp.remove(name) else "Pick a server first."
            return (note, *tools_refresh())

        # ------------------------------------------------------------------ search
        def search(query: str, k: int, scope: str = ""):
            if not (query or "").strip():
                return "<p class='lm-muted'>Type something to search for.</p>"
            results = rag_engine.search_hybrid(query, top_k=int(k), scope=scope or "")
            if not results:
                return "<p class='lm-muted'>No matches in your documents.</p>"
            cards = []
            for i, r in enumerate(results, 1):
                page = f" · page {r.page_number}" if r.page_number not in (None, -1) else ""
                cards.append(
                    "<div class='hit-card'>"
                    f"<div class='hit-meta'><span class='hit-score'>{r.score:.3f}</span>#{i} · {html.escape(r.source)}{page} · {html.escape(sections.section_of(r.source))}</div>"
                    f"<div class='hit-text'>{html.escape(r.text[:900])}</div></div>"
                )
            return "".join(cards)

        TOOLS_OUT = [requests_view, request_pick, skills_view, skill_pick, mcp_view, mcp_pick]
        queue_btn.click(
            queue_tasks, [task_name, task_instructions, task_items, task_files, task_model, task_scope, task_kb, task_web, task_think],
            [queue_status, queue_view, task_items, task_files, nav_tasks], show_progress="minimal",
        )
        cancel_tasks_btn.click(cancel_tasks, None, [queue_status, queue_view], show_progress="hidden")
        retry_tasks_btn.click(retry_tasks, None, [queue_status, queue_view], show_progress="hidden")
        approve_btn.click(lambda rid: decide(rid, True), [request_pick], [tools_status, *TOOLS_OUT], show_progress="minimal")
        deny_btn.click(lambda rid: decide(rid, False), [request_pick], [tools_status, *TOOLS_OUT], show_progress="hidden")
        install_skill_btn.click(install_skill, [skill_url], [tools_status, *TOOLS_OUT, skill_url], show_progress="minimal")
        remove_skill_btn.click(remove_skill, [skill_pick], [tools_status, *TOOLS_OUT], show_progress="hidden")
        add_mcp_btn.click(add_mcp, [mcp_name, mcp_target], [tools_status, *TOOLS_OUT, mcp_name, mcp_target], show_progress="minimal")
        remove_mcp_btn.click(remove_mcp, [mcp_pick], [tools_status, *TOOLS_OUT], show_progress="hidden")

        def tasks_tick(view_is):
            # Cheap: two small reads. Keeps the queue, approvals and sidebar counts current.
            labels = sidebar_labels()
            if view_is == "tasks":
                return (queue_html(), *labels, *(gr.skip(),) * len(TOOLS_OUT))
            if view_is == "tools":
                return (gr.skip(), *labels, *tools_refresh())
            return (gr.skip(), *labels, *(gr.skip(),) * len(TOOLS_OUT))

        current_view = gr.State("chat")
        tasks_timer.tick(tasks_tick, [current_view], [queue_view, nav_tasks, nav_tools, *TOOLS_OUT], show_progress="hidden",
                         concurrency_limit=None, concurrency_id="tasks")
        nav_tasks.click(lambda: nav("tasks"), outputs=NAV_OUT, show_progress="hidden", queue=False).then(
            lambda: ("tasks", queue_html(), gr.Dropdown(choices=scope_choices())), outputs=[current_view, queue_view, task_scope], show_progress="hidden")
        nav_tools.click(lambda: nav("tools"), outputs=NAV_OUT, show_progress="hidden", queue=False).then(
            lambda: ("tools", *tools_refresh()), outputs=[current_view, *TOOLS_OUT], show_progress="hidden")
        for other, view in ((nav_chat, "chat"), (nav_kb, "kb"), (nav_search, "search")):
            other.click(lambda v=view: v, outputs=[current_view], show_progress="hidden", queue=False)

        search_btn.click(search, [search_input, top_k, scope_dd], [search_results], show_progress="minimal")
        search_input.submit(search, [search_input, top_k, scope_dd], [search_results], show_progress="minimal")

        # The follower goes last: it may run for as long as a reload-interrupted answer takes.
        app.load(bootstrap, outputs=[*CHAT_OUT, kb_mini], show_progress="hidden").then(
            refresh_kb, outputs=[kb_head, sources_table, kb_mini], show_progress="hidden"
        ).then(sections_html, outputs=[sections_view], show_progress="hidden").then(
            remeasure, [conv_id, model_dd, think_on, kv_dd], [ctx_state, hud_view], show_progress="hidden"
        ).then(follow, [conv_id, ctx_state], FOLLOW_OUT, show_progress="hidden", concurrency_limit=None, concurrency_id="follow")

    return app
