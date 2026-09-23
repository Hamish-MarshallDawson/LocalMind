from __future__ import annotations

import logging
from pathlib import Path

import click
from rich.console import Console
from rich.logging import RichHandler

console = Console()


def setup_logging(verbose: bool = False):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(message)s",
        handlers=[RichHandler(console=console, rich_tracebacks=True)],
    )


def build_app(config_path: str = "config.yaml"):
    from localmind.agent.orchestrator import Agent
    from localmind.config import load_config
    from localmind.models.manager import ModelManager
    from localmind.rag.engine import RAGEngine
    from localmind.tools.builtins import register_builtin_tools
    from localmind.tools.registry import ToolRegistry

    config = load_config(config_path)
    model_manager = ModelManager(config)
    rag_engine = RAGEngine(config, model_manager)
    tool_registry = ToolRegistry()
    register_builtin_tools(tool_registry, config, rag_engine)
    agent = Agent(config, model_manager, tool_registry)

    return config, model_manager, rag_engine, agent


@click.group()
@click.option("--config", default="config.yaml", help="Path to config file")
@click.option("-v", "--verbose", is_flag=True, help="Verbose logging")
@click.pass_context
def main(ctx, config, verbose):
    """LocalMind - Local multimodal RAG system"""
    setup_logging(verbose)
    ctx.ensure_object(dict)
    ctx.obj["config_path"] = config


@main.command()
@click.pass_context
def chat(ctx):
    """Start an interactive chat session."""
    config, model_manager, rag_engine, agent = build_app(ctx.obj["config_path"])

    console.print("[bold green]LocalMind[/] ready. Type 'quit' to exit, 'reset' to clear history.")
    console.print(f"Knowledge base: {rag_engine.count()} chunks indexed.\n")

    while True:
        try:
            user_input = console.input("[bold blue]You:[/] ")
        except (EOFError, KeyboardInterrupt):
            break

        if user_input.strip().lower() in ("quit", "exit"):
            break
        if user_input.strip().lower() == "reset":
            agent.reset()
            console.print("[dim]History cleared.[/dim]\n")
            continue
        if not user_input.strip():
            continue

        console.print()
        for event in agent.stream(user_input):
            if event.kind == "tool_call":
                args = ", ".join(f"{k}={v!r}" for k, v in event.arguments.items())
                console.print(f"  [dim]→ {event.name}({args})[/dim]")
            elif event.kind == "tool_result":
                console.print(f"  [dim]  {len(event.text)} chars in {event.duration:.1f}s[/dim]")
            elif event.kind == "answer":
                console.print(f"\n[bold green]LocalMind:[/] {event.text}\n")
            elif event.kind == "error":
                console.print(f"\n[bold red]Error:[/] {event.text}\n")


@main.command()
@click.argument("paths", nargs=-1, required=True, type=click.Path(exists=True))
@click.pass_context
def ingest(ctx, paths):
    """Ingest documents into the knowledge base."""
    from localmind.config import load_config
    from localmind.ingest.pipeline import IngestPipeline
    from localmind.models.manager import ModelManager
    from localmind.rag.engine import RAGEngine

    config = load_config(ctx.obj["config_path"])
    model_manager = ModelManager(config)
    rag_engine = RAGEngine(config, model_manager)
    pipeline = IngestPipeline(config, model_manager)

    for path_str in paths:
        path = Path(path_str)
        if path.is_dir():
            results = pipeline.ingest_directory(path)
            for result in results:
                chunks = pipeline.process_to_chunks(result.source)
                rag_engine.add_chunks(chunks)
                console.print(f"  [green]✓[/] {result.source.name}: {result.num_pages} pages, {result.num_chunks} chunks")
        else:
            chunks = pipeline.process_to_chunks(path)
            count = rag_engine.add_chunks(chunks)
            console.print(f"  [green]✓[/] {path.name}: {count} chunks added")

    console.print(f"\n[bold]Total: {rag_engine.count()} chunks in knowledge base.[/]")


@main.command()
@click.pass_context
def sources(ctx):
    """List all ingested document sources."""
    from localmind.config import load_config
    from localmind.models.manager import ModelManager
    from localmind.rag.engine import RAGEngine

    config = load_config(ctx.obj["config_path"])
    model_manager = ModelManager(config)
    rag_engine = RAGEngine(config, model_manager)

    source_list = rag_engine.list_sources()
    if not source_list:
        console.print("[dim]No documents ingested yet.[/dim]")
        return

    for source in source_list:
        console.print(f"  • {source}")
    console.print(f"\n[bold]{len(source_list)} sources, {rag_engine.count()} total chunks.[/]")


def prepare_server(config_path: str = "config.yaml", *, lan: bool = False, auto_shutdown: bool = False, adjust=None):
    """Everything `serve` runs, ready to launch. `adjust(config)` lets tests change settings."""
    import atexit
    import time
    from types import SimpleNamespace

    from localmind.llm.kvcache import KV_CACHE_TYPES
    from localmind.metrics import gpu_stats
    from localmind.network import ensure_certificate, lan_addresses, plan
    from localmind.power import PowerManager
    from localmind.remote import GatewayReporter, host_info
    from localmind.storage import ConversationStore
    from localmind.ui.app import create_ui
    from localmind.ui.remote_api import remote_routes
    from localmind.ui.theme import CSS, JS, THEME
    from localmind.ui.turns import TurnManager
    from localmind.ui.voice_routes import voice_routes
    from localmind.voice import VoiceEngine
    from localmind.extensions import Extensions
    from localmind.ui.tasks import TaskQueue

    config, model_manager, rag_engine, agent = build_app(config_path)
    if adjust:
        adjust(config)
    serve_plan = plan(config.server, lan=lan)  # raises UnsafeExposure before anything loads

    hub = agent.hub
    store = ConversationStore(config.storage.conversations_db)
    turns = TurnManager(agent, rag_engine, store, config)
    voice = VoiceEngine(config.voice, model_manager, on_gpu_change=hub.forget_windows)
    started = time.time()
    state = SimpleNamespace(power=None, reporter=None)
    notify = lambda: state.reporter and state.reporter.notify()  # noqa: E731 - reporter is made below
    data_dir = Path(config.storage.conversations_db).parent
    tasks = TaskQueue(data_dir / "tasks.db", turns, on_change=notify)
    extensions = Extensions(data_dir, agent.tool_registry, agent, on_change=notify)

    def snapshot() -> dict:
        """What the gateway shows about this PC, including after it has shut down."""
        gpu = gpu_stats()
        loaded = model_manager.loaded_chat_model
        power = state.power.status() if state.power else {}
        return {
            **host_info(),
            "state": "shutting_down" if power.get("shutdown_at") else "online",
            "started_at": started,
            "uptime_seconds": round(time.time() - started),
            "urls": serve_plan.urls,
            "models": [
                {"key": s.key, "label": s.label, "cloud": s.is_cloud, "thinking": s.thinking, "vision": s.vision}
                for s in hub.specs.values()
            ],
            "default_model": hub.default_key,
            "kv_types": [{"key": t.key, "label": t.label, "description": t.description} for t in KV_CACHE_TYPES.values()],
            "default_kv": config.chat_models.default_kv_cache,
            "sections": rag_engine.sections.sections(),
            "loaded_model": next((s.label for s in hub.specs.values() if loaded and s.model == loaded), loaded),
            "gpu": {"name": gpu.name, "used_gb": round(gpu.used_gb, 2), "total_gb": round(gpu.total_gb, 2), "util_percent": gpu.util_percent} if gpu else None,
            "running": sorted(turns.running()),
            "power": power,
            "tasks": tasks.summary(),
            "extensions": extensions.snapshot(),
        }

    reporter = GatewayReporter(config.gateway, snapshot, store)
    state.reporter = reporter
    power = PowerManager(
        config.power,
        enabled=auto_shutdown,
        # Waiting tasks count too: the PC mustn't switch off between two queued CVs.
        running_turns=lambda: turns.running() | tasks.active_chats(),
        # The gateway's record of why the PC went off, sent while it still can be.
        before_shutdown=lambda reason: reporter.report("shutting_down", reason),
        on_change=reporter.notify,
    )
    state.power = power
    turns.on_start.append(lambda turn: power.touch("a message"))
    turns.on_done.append(lambda turn: reporter.notify())
    atexit.register(lambda: power.shutdown_at is None and reporter.report("stopped", "LocalMind was closed"))

    app = create_ui(agent, rag_engine, voice, store=store, turns=turns, tasks=tasks, extensions=extensions)
    tls = {}
    if serve_plan.https:
        cert, key = ensure_certificate(config.server.certificate_dir, lan_addresses())
        tls = {"ssl_certfile": str(cert), "ssl_keyfile": str(key), "ssl_verify": False}
    launch_kwargs = dict(
        server_name=serve_plan.host,
        server_port=serve_plan.port,
        theme=THEME,
        css=CSS,
        js=JS,
        auth=serve_plan.auth,
        auth_message="LocalMind" if serve_plan.auth else None,
        # Voice audio and the gateway's API join Gradio's own app: voice behind the same login,
        # the gateway API behind its shared token.
        app_kwargs={"routes": voice_routes(voice) + remote_routes(turns, store, power, snapshot, extensions=extensions)},
        **tls,
    )

    def start_background():
        reporter.start()
        power.start()
        extensions.start()  # reconnects saved MCP servers
        tasks.start()

    return SimpleNamespace(
        app=app, launch_kwargs=launch_kwargs, plan=serve_plan, config=config, power=power,
        reporter=reporter, turns=turns, store=store, tasks=tasks, extensions=extensions, start_background=start_background,
    )


@main.command()
@click.option("--lan", is_flag=True, help="Allow phones and other computers on your network to connect (needs LOCALMIND_PASSWORD).")
@click.option("--auto-shutdown", is_flag=True, help="Shut the PC down after power.idle_shutdown_minutes without activity.")
@click.pass_context
def serve(ctx, lan, auto_shutdown):
    """Start the Gradio web UI."""
    from localmind.network import UnsafeExposure

    try:
        server = prepare_server(ctx.obj["config_path"], lan=lan, auto_shutdown=auto_shutdown)
    except UnsafeExposure as e:
        console.print(f"[bold red]{e}[/]")
        raise SystemExit(2) from None

    serve_plan = server.plan
    if serve_plan.lan:
        console.print("\n[bold green]LocalMind is open to your network.[/] Open one of these on another device:")
        for url in serve_plan.urls:
            console.print(f"   [bold]{url}[/]")
        console.print(f"Sign in as [bold]{serve_plan.auth[0]}[/] with LOCALMIND_PASSWORD." if serve_plan.auth else "[yellow]No password set.[/]")
        if serve_plan.https:
            console.print(
                "[dim]HTTPS uses a certificate made on this PC, so each browser warns once: choose "
                "Advanced > Continue. It's needed for the microphone (Voice) on other devices.[/]"
            )
        console.print(
            "[dim]If other devices can't connect, allow Python through Windows Defender Firewall "
            "for private networks (Windows usually asks on first launch).[/]\n"
        )
    if server.power.enabled:
        console.print(f"[yellow]Auto-shutdown is on:[/] this PC turns off after {server.config.power.idle_shutdown_minutes:g} minutes without activity.")

    server.start_background()
    server.app.launch(**server.launch_kwargs)


if __name__ == "__main__":
    main()
