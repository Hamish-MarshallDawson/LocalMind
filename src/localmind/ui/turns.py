"""Chat turns that run independently of whoever is watching them.

A turn used to live inside the Gradio event that sent the message, so opening another chat
cancelled the event and with it the answer. Now a turn runs on its own thread; the UI merely
*follows* it. Switching chats stops following, never the turn, and coming back resumes the view
from wherever the answer has got to. Progress is saved as it goes, so a page reload loses nothing.

Local models share one GPU, so local turns queue behind each other; cloud turns don't wait.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image

from localmind.agent.messages import normalize_transcript
from localmind.agent.orchestrator import Agent
from localmind.rag.sections import current_scope
from localmind.tools.documents import current_chat
from localmind.storage import title_from_message

from .render import TurnRenderer

logger = logging.getLogger(__name__)

SAVE_INTERVAL = 2.0  # seconds between progress checkpoints while a turn runs
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}
FORCE_TOOL_NAMES = {"web": "web_search", "kb": "knowledge_search"}


class TurnBusy(RuntimeError):
    """The chat is still answering its previous message."""


@dataclass
class TurnRequest:
    cid: str
    text: str
    images: list[Path] = field(default_factory=list)
    documents: list[Path] = field(default_factory=list)
    model_key: str | None = None
    thinking: bool = False
    force_tools: list[str] = field(default_factory=list)
    kv_cache: str | None = None
    voice: bool = False  # the reply will be spoken, so ask for one that reads well aloud
    scope: str = ""  # knowledge-base section this chat may search (plus shared ones); "" = all


class Turn:
    """Shared, thread-safe view of one running turn."""

    def __init__(self, request: TurnRequest, history: list[dict], context: dict | None):
        self.request = request
        self.cid = request.cid
        self.cancel = threading.Event()
        self._cond = threading.Condition()
        self._history = list(history)
        self._status: str | None = "Queued"
        self._context = context
        self._done = False
        self._version = 0
        self.started_at = time.time()

    def publish(self, history: list[dict], status: str | None, context: dict | None, done: bool = False) -> None:
        with self._cond:
            self._history = [dict(m) if isinstance(m, dict) else m for m in history]
            for message in self._history:
                if isinstance(message, dict) and isinstance(message.get("metadata"), dict):
                    message["metadata"] = dict(message["metadata"])
            self._status, self._context, self._done = status, context, done
            self._version += 1
            self._cond.notify_all()

    def snapshot(self) -> tuple[int, list[dict], str | None, dict | None, bool]:
        with self._cond:
            return self._version, self._history, self._status, self._context, self._done

    def wait(self, since_version: int, timeout: float) -> None:
        with self._cond:
            if self._version == since_version and not self._done:
                self._cond.wait(timeout)

    @property
    def done(self) -> bool:
        with self._cond:
            return self._done


class TurnManager:
    def __init__(self, agent: Agent, rag_engine, store, config, on_context=None):
        self.agent = agent
        self.rag_engine = rag_engine
        self.store = store
        self.config = config
        self.on_context = on_context  # (cid, context, spec) -> context; e.g. to raise a warning
        self._turns: dict[str, Turn] = {}
        self._lock = threading.Lock()
        self._gpu = threading.Lock()
        self.on_start: list = []  # callbacks(turn) - e.g. to count a message as activity
        self.on_done: list = []  # callbacks(turn) - e.g. to report the answer to the gateway

    # ------------------------------------------------------------------ public
    def get(self, cid: str | None) -> Turn | None:
        if not cid:
            return None
        with self._lock:
            return self._turns.get(cid)

    def running(self) -> set[str]:
        with self._lock:
            return {cid for cid, turn in self._turns.items() if not turn.done}

    def is_running(self, cid: str | None) -> bool:
        turn = self.get(cid)
        return bool(turn and not turn.done)

    def submit(
        self,
        *,
        cid: str | None,
        text: str,
        files=(),
        model_key: str | None = None,
        web: bool = False,
        kb: bool = False,
        thinking: bool = False,
        kv: str | None = None,
        voice: bool = False,
        scope: str = "",
        history: list[dict] | None = None,
    ) -> tuple[str, list[dict], Turn, str]:
        """Record a message in a chat and start answering it: the web UI and the gateway API both
        come through here. Returns (chat id, history including the new message, turn, title)."""
        store, hub = self.store, self.agent.hub
        text = (text or "").strip()
        files = [Path(f) for f in files]
        if not cid or store.get(cid) is None:
            cid = store.create(cid=cid)
        if self.is_running(cid):
            raise TurnBusy("This chat is still answering. Stop it first, or open another chat.")

        spec = hub.spec(model_key)
        history = list(store.load(cid)[0] if history is None else history)
        first_turn = not history
        images = [f for f in files if f.suffix.lower() in IMAGE_EXTS]
        documents = [f for f in files if f.suffix.lower() not in IMAGE_EXTS]
        history.extend({"role": "user", "content": {"path": str(f)}} for f in images)
        if text:
            history.append({"role": "user", "content": text})
        history.extend({"role": "user", "content": f"📎 {doc.name}"} for doc in documents)

        # Name the chat immediately so the sidebar updates the moment you hit send.
        conv = store.get(cid)
        title = conv.title if conv else ""
        if first_turn:
            title = title_from_message(text or (files[0].name if files else ""))
            store.rename(cid, title)
        store.touch(cid)
        store.update_settings(cid, model=spec.key, thinking=thinking, web=web, kb=kb, kv=kv, scope=scope or "")
        store.save(cid, history, store.load(cid)[1])

        force = [FORCE_TOOL_NAMES["web"]] * bool(web) + [FORCE_TOOL_NAMES["kb"]] * bool(kb)
        request = TurnRequest(
            cid=cid, text=text, images=images, documents=documents, model_key=spec.key,
            thinking=thinking, force_tools=force, kv_cache=kv if not spec.is_cloud else None, voice=voice,
            scope=scope or "",
        )
        turn = self.start(request, history, store.get_settings(cid).get("context"))
        return cid, history, turn, title

    def start(self, request: TurnRequest, history: list[dict], context: dict | None) -> Turn:
        with self._lock:
            existing = self._turns.get(request.cid)
            if existing and not existing.done:
                raise RuntimeError("This chat is still answering the previous message.")
            turn = Turn(request, history, context)
            self._turns[request.cid] = turn
        turn.publish(history, "Queued" if self._gpu.locked() else "Thinking", context)
        for callback in self.on_start:
            callback(turn)
        threading.Thread(target=self._run, args=(turn,), name=f"turn-{request.cid}", daemon=True).start()
        return turn

    def cancel(self, cid: str | None) -> bool:
        turn = self.get(cid)
        if turn and not turn.done:
            turn.cancel.set()
            return True
        return False

    # ------------------------------------------------------------------ worker
    def _run(self, turn: Turn) -> None:
        request = turn.request
        current_scope.set(request.scope)  # this thread's knowledge_search sees only its sections
        current_chat.set(request.cid)  # files this turn writes go in the chat's own folder
        spec = self.agent.hub.spec(request.model_key)
        renderer = TurnRenderer(turn.snapshot()[1])
        context = turn.snapshot()[3]
        display_saved_at = 0.0

        def checkpoint(status: str | None, force: bool = False) -> None:
            nonlocal display_saved_at
            turn.publish(renderer.history, status, context)
            now = time.monotonic()
            if force or now - display_saved_at >= SAVE_INTERVAL:
                display_saved_at = now
                try:
                    self.store.save(request.cid, renderer.history, transcript)
                except Exception:  # noqa: BLE001
                    logger.exception("Checkpoint save failed for %s", request.cid)

        transcript = normalize_transcript(self.store.load(request.cid)[1])
        gpu = self._gpu if not spec.is_cloud else None
        completed = False
        try:
            if gpu is not None and not gpu.acquire(blocking=False):
                checkpoint("Waiting for another chat to finish", force=True)
                while not gpu.acquire(timeout=0.5):
                    if turn.cancel.is_set():
                        gpu = None
                        renderer.stopped()
                        return
            try:
                images = self._open_images(request, renderer)
                message = self._index_documents(request, renderer, checkpoint)
                for event in self.agent.stream(
                    message,
                    images=images,
                    model_key=spec.key,
                    thinking=request.thinking,
                    force_tools=request.force_tools,
                    kv_cache=request.kv_cache,
                    transcript=transcript,
                    cancel=turn.cancel,
                    voice=request.voice,
                ):
                    status = renderer.apply(event)
                    if event.kind == "usage":
                        context = {**event.data, "warned_for": (context or {}).get("warned_for", [])}
                        if self.on_context:
                            context = self.on_context(request.cid, context, spec) or context
                    checkpoint(status, force=event.kind in ("tool_result", "answer", "error"))
                completed = not turn.cancel.is_set()
            finally:
                if gpu is not None:
                    gpu.release()
        except Exception as e:  # noqa: BLE001 - a crashed turn must still end cleanly
            logger.exception("Turn failed for %s", request.cid)
            renderer.error(str(e))
        finally:
            if not completed:
                renderer.stopped()
            try:
                self.store.save(request.cid, renderer.history, transcript)
                self.store.update_settings(request.cid, context=context)
            except Exception:  # noqa: BLE001
                logger.exception("Final save failed for %s", request.cid)
            turn.publish(renderer.history, None, context, done=True)
            for callback in self.on_done:
                try:
                    callback(turn)
                except Exception:  # noqa: BLE001 - a reporting hiccup must not break the turn
                    logger.exception("Turn-finished callback failed")

    def _open_images(self, request: TurnRequest, renderer: TurnRenderer) -> list[Image.Image]:
        images = []
        for path in request.images:
            try:
                images.append(Image.open(path).convert("RGB"))
            except Exception as e:  # noqa: BLE001
                renderer.note(f"Couldn't open image {path.name}: {e}")
        return images

    def _index_documents(self, request: TurnRequest, renderer: TurnRenderer, checkpoint) -> str:
        message = request.text or ("What's in this image?" if request.images else "Please look at the attached documents.")
        if not request.documents:
            return message

        from localmind.ingest.pipeline import IngestPipeline

        pipeline = IngestPipeline(self.config, self.agent.model_manager)
        indexed = []
        for doc in request.documents:
            panel = renderer.panel(f"📥 Indexing {doc.name}")
            checkpoint(f"Indexing {doc.name}")
            started = time.perf_counter()
            try:
                count = self.rag_engine.add_chunks(pipeline.process_to_chunks(doc, source_name=doc.name))
                if request.scope:  # filed with the chat's section, so other sections can't see it
                    self.rag_engine.sections.assign(doc.name, request.scope)
                renderer.finish_panel(panel, f"Added **{count}** chunks to your knowledge base.", time.perf_counter() - started)
                indexed.append(doc.name)
            except Exception as e:  # noqa: BLE001
                logger.exception("Ingest failed for %s", doc)
                renderer.finish_panel(panel, f"⚠️ Couldn't index this file: {e}", time.perf_counter() - started)
        if indexed:
            message += f"\n\n[Attached and indexed into the knowledge base: {', '.join(indexed)}. Use knowledge_search to read them.]"
        return message
