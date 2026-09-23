"""Hugging Face transformers backend for local chat models (Qwen3-VL, Gemma 4, ...)."""
from __future__ import annotations

import logging
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass

import torch

from .kvcache import decode_transient_per_token, kv_bytes_per_token, kv_type, make_cache
from .parsers import OutputParser, parser_for
from .types import Chunk, ModelSpec, RoundResult

logger = logging.getLogger(__name__)

GIB = 2**30
PREFILL_CHUNK = 2048  # prompt tokens per forward pass; bounds activation memory for long contexts
PREFILL_HEADROOM_GIB = 1.2  # activations for one prefill chunk + generation workspace (measured ~0.75)
VRAM_USABLE = 0.95  # fraction of the card we plan to fill; the rest absorbs other apps growing


@dataclass
class Progress:
    """A status update from inside generation (e.g. reading a long prompt)."""

    text: str


def _short(n: int) -> str:
    return f"{n / 1000:.0f}K" if n >= 1000 else str(n)


def template_messages(messages: list[dict]) -> list[dict]:
    """Drop in-memory-only keys ("_provider", "_scaffold", ...) before rendering."""
    return [{k: v for k, v in m.items() if not k.startswith("_")} for m in messages]


def collect_images(messages: list[dict]) -> list:
    """PIL images in prompt order - the processor pairs them with the template's placeholders."""
    images = []
    for message in messages:
        content = message.get("content")
        if isinstance(content, list):
            images.extend(part["image"] for part in content if isinstance(part, dict) and part.get("type") == "image" and part.get("image") is not None)
    return images


def first_parameter(tools: list[dict] | None, name: str) -> str:
    for tool in tools or []:
        fn = tool.get("function", {})
        if fn.get("name") == name:
            params = fn.get("parameters", {})
            required = params.get("required") or list(params.get("properties", {}))
            if required:
                return required[0]
    return "query"


class LocalBackend:
    def __init__(self, spec: ModelSpec, model_manager, config):
        self.spec = spec
        self.model_manager = model_manager
        self.config = config
        self.parser: OutputParser = parser_for(spec.family)
        self._windows: dict[tuple[str, str], tuple[float, int]] = {}
        self._model_config = None

    # ------------------------------------------------------------------ model selection
    def repo(self, thinking: bool) -> str:
        if thinking and self.spec.thinking == "variant" and self.spec.thinking_model:
            return self.spec.thinking_model
        return self.spec.model

    def load_notice(self, thinking: bool) -> str | None:
        """A status line when this round must load (and maybe download) weights first."""
        repo = self.repo(thinking)
        if self.model_manager.loaded_chat_model == repo:
            return None
        name = repo.split("/")[-1]
        return f"Loading {name}" + (" (first use downloads the weights)" if repo != self.spec.model else "")

    # ------------------------------------------------------------------ context budget
    def forget_windows(self) -> None:
        """Re-estimate on next use: something else (Whisper, say) just took or freed VRAM."""
        self._windows.clear()

    def context_window(self, kv_cache: str | None = None) -> int:
        """Tokens that fit on this GPU with the chosen KV cache type, capped at the model maximum."""
        kind = kv_type(kv_cache).key
        key = (self.spec.model, kind)
        cached = self._windows.get(key)
        # Re-estimate now and then: other apps' VRAM use changes, and a one-off busy moment
        # (a game, another model) shouldn't shrink the window for the rest of the session.
        if cached is None or time.monotonic() - cached[0] > self.WINDOW_TTL:
            try:
                window = self._estimate_window(kind)
            except Exception as e:  # noqa: BLE001 - never let a meter break a turn
                logger.warning("Context window estimate failed (%s); using the configured %d", e, self.spec.context_window)
                window = self.spec.context_window
            cached = (time.monotonic(), window)
            self._windows[key] = cached
        return cached[1]

    WINDOW_TTL = 120.0

    def _estimate_window(self, kind: str) -> int:
        from transformers import AutoConfig

        if self._model_config is None:
            self._model_config = AutoConfig.from_pretrained(self.spec.model)
        model_config = self._model_config
        text = model_config.get_text_config(decoder=True)
        model_max = int(getattr(text, "max_position_embeddings", None) or self.spec.context_window)
        if not torch.cuda.is_available():
            return min(self.spec.context_window, model_max)

        if kind == "offload":
            budget = _available_ram() * 0.5  # leave the other half for the OS, Python and tools
            per_token = kv_bytes_per_token(model_config, "bf16", model_max)
            gpu_budget = torch.cuda.get_device_properties(0).total_memory * VRAM_USABLE - _other_processes_vram() - (self.spec.weights_gb + PREFILL_HEADROOM_GIB) * GIB
            gpu_per_token = self.spec.attention_transient_kb * 1024 + decode_transient_per_token(model_config)
            budget = min(budget, max(gpu_budget, 0) * per_token / max(gpu_per_token, 1))
        else:
            total = torch.cuda.get_device_properties(0).total_memory
            budget = total * VRAM_USABLE - _other_processes_vram() - self.spec.weights_gb * GIB - PREFILL_HEADROOM_GIB * GIB
            # KV storage, plus what attention itself needs per token at run time (measured per model:
            # Qwen3-VL expands its 8 KV heads to 32 query heads for each layer as it attends).
            per_token = kv_bytes_per_token(model_config, kind, model_max) + self.spec.attention_transient_kb * 1024
            if kind in ("fp8", "int4"):
                per_token += decode_transient_per_token(model_config)
        window = int(max(budget, 0) // max(per_token, 1))
        window = max(4096, min(model_max, (window // 1024) * 1024))
        logger.info("%s with %s KV cache: ~%d tokens of context", self.spec.label, kind, window)
        return window

    def _template_kwargs(self, thinking: bool) -> dict:
        return {"enable_thinking": bool(thinking)} if self.spec.thinking == "native" else {}

    # ------------------------------------------------------------------ prompts
    def render(self, processor, messages: list[dict], tools: list[dict] | None, thinking: bool) -> str:
        # Render to text, then run the processor ourselves: passing template flags such as
        # enable_thinking through a tokenizing apply_chat_template makes transformers forward them
        # to processor.__call__, which warns and drops them.
        return processor.apply_chat_template(
            template_messages(messages),
            tools=tools,
            add_generation_prompt=True,
            tokenize=False,
            **self._template_kwargs(thinking),
        )

    @staticmethod
    def encode(processor, prompt: str, images: list) -> dict:
        kwargs = {"text": [prompt], "return_tensors": "pt", "add_special_tokens": False}
        if images:
            kwargs["images"] = images
        return processor(**kwargs)

    def count_tokens(self, messages: list[dict], tools: list[dict] | None, thinking: bool) -> tuple[int, bool]:
        processor = self.model_manager.get_processor(self.repo(thinking))
        prompt = self.render(processor, messages, tools, thinking)
        return int(self.encode(processor, prompt, collect_images(messages))["input_ids"].shape[1]), True

    # ------------------------------------------------------------------ one generation round
    def stream_round(
        self,
        messages: list[dict],
        tools: list[dict] | None,
        *,
        thinking: bool,
        force_tool: str | None,
        cancel: threading.Event,
        kv_cache: str | None = None,
    ) -> Iterator[Chunk | RoundResult]:
        opens, prefix, pieces, prompt_tokens = self._generate(messages, tools, thinking, force_tool, cancel, kv_cache)
        parser = self.parser

        raw = prefix
        for piece in pieces:
            if isinstance(piece, Progress):
                yield Chunk("status", piece.text)
                continue
            raw += piece
            thinking_text, body = parser.split_thinking(raw, opens=opens, partial=True)
            if thinking_text:
                yield Chunk("thinking", thinking_text)
            visible, calling = parser.visible_partial(body)
            yield Chunk("calling") if calling else Chunk("text", visible)

        thinking_text, body = parser.split_thinking(raw, opens=opens, partial=False)
        calls = parser.tool_calls(body)
        text = parser.visible_partial(body)[0] if calls else parser.clean(body)
        generated = self._token_len(raw[len(prefix):])
        yield RoundResult(
            text=text,
            thinking=thinking_text,
            tool_calls=calls,
            context_tokens=(prompt_tokens + generated) if prompt_tokens is not None else None,
        )

    def _token_len(self, text: str) -> int:
        try:
            processor = self.model_manager.get_processor(self.spec.model)
            return len(getattr(processor, "tokenizer", processor).encode(text, add_special_tokens=False))
        except Exception:  # noqa: BLE001
            return len(text) // 4

    # Reasoning before a forced tool call is capped so the model can't stall the call indefinitely.
    FORCED_THINKING_TOKENS = 2048
    _END_TOKENS = ("<turn|>", "<|im_end|>", "<eos>", "<|endoftext|>")

    def _generate(self, messages, tools, thinking, force_tool, cancel, kv_cache=None):
        """Returns (prompt_opens_thinking, prefix, text_pieces, prompt_token_count).

        `prefix` is text already fixed in the model's reply before generation starts; `text_pieces`
        continues it. Parsing always runs over prefix + pieces.
        """
        model, processor, prompt, images, stop_ids = self._prepare(messages, tools, thinking)
        opens = self.parser.prompt_opens_thinking(prompt)
        prompt_tokens = self._count_prompt(processor, prompt, images)
        max_new = min(self.spec.max_output_tokens, self.config.models.chat.max_new_tokens)

        if not force_tool:
            return opens, "", self._stream(model, processor, prompt, images, stop_ids, cancel, max_new, kv_cache), prompt_tokens

        # Prefill the start of the tool call: the model can only continue by writing its arguments.
        # This is the local equivalent of Anthropic's tool_choice={"type": "tool"}.
        call_prefix = self.parser.forced_call_prefix(force_tool, first_parameter(tools, force_tool))
        if not thinking:
            prefix = (self.parser.close_thinking() if opens else "") + call_prefix
            return opens, prefix, self._stream(model, processor, prompt + prefix, images, stop_ids, cancel, max_new, kv_cache), prompt_tokens

        # Thinking on: reason first, then make the forced call. Models like Gemma 4 only reason at
        # the start of a turn - once a tool result is in, they close the thought channel at once -
        # so prefilling the call straight away would mean no visible reasoning at all.
        opener = "" if opens else self.parser.thinking_open
        close_ids = self._token_ids(processor, [self.parser.thinking_close_token])

        def pieces() -> Iterator[str]:
            thought, closed = "", False
            for piece in self._stream(model, processor, prompt + opener, images, stop_ids | close_ids, cancel, self.FORCED_THINKING_TOKENS, kv_cache):
                if not isinstance(piece, str):
                    yield piece
                    continue
                if piece.strip() in self._END_TOKENS:
                    continue
                thought += piece
                yield piece
                if self.parser.thinking_close_token and self.parser.thinking_close_token in piece:
                    # No break: the close token is a stop token, so generation ends here anyway,
                    # and abandoning the stream early would trigger its cancel-on-disconnect cleanup.
                    closed = True
            if cancel.is_set():
                return
            bridge = ("" if closed else self.parser.close_thinking()) + call_prefix
            yield bridge
            yield from self._stream(model, processor, prompt + opener + thought + bridge, images, stop_ids, cancel, max_new, kv_cache)

        return False, opener, pieces(), prompt_tokens

    # ------------------------------------------------------------------ transformers plumbing
    def _prepare(self, messages, tools, thinking):
        model, processor = self.model_manager.get_chat_model(self.repo(thinking))
        prompt = self.render(processor, messages, tools, thinking)
        stop_ids = self._token_ids(processor, self.parser.stop_tokens)
        eos = getattr(model.generation_config, "eos_token_id", None)
        stop_ids.update(eos if isinstance(eos, list) else [eos] if eos is not None else [])
        return model, processor, prompt, collect_images(messages), stop_ids

    @staticmethod
    def _token_ids(processor, tokens) -> set[int]:
        tokenizer = getattr(processor, "tokenizer", processor)
        ids = set()
        for token in tokens:
            if token:
                encoded = tokenizer.encode(token, add_special_tokens=False)
                if len(encoded) == 1:
                    ids.add(encoded[0])
        return ids

    def _count_prompt(self, processor, prompt: str, images: list) -> int:
        return int(self.encode(processor, prompt, images)["input_ids"].shape[1])

    def _prefill(self, model, input_ids, attention_mask, cache, cancel: threading.Event) -> Iterator[Progress]:
        """Feed all but the last prompt token through the model in chunks, filling `cache`.

        Prefilling a long prompt in one pass needs activation memory proportional to its length
        (a 62K prompt alone needed ~14 GB). Chunks keep that flat, which is what lets the KV cache
        type - not prefill - decide how much context fits.
        """
        total = input_ids.shape[1] - 1
        inner = getattr(model, "model", None)
        mrope = inner is not None and hasattr(inner, "rope_deltas")
        if mrope:
            # Qwen-VL keeps rope offsets from the previous call; stale ones corrupt chunk positions.
            inner.rope_deltas = None
        with torch.inference_mode():
            for start in range(0, total, PREFILL_CHUNK):
                if cancel.is_set():
                    return
                end = min(start + PREFILL_CHUNK, total)
                positions = torch.arange(start, end, device=input_ids.device).view(1, 1, -1)
                model(
                    input_ids=input_ids[:, start:end],
                    attention_mask=attention_mask[:, :end] if attention_mask is not None else None,
                    position_ids=positions.expand(3, 1, -1) if mrope else positions.view(1, -1),
                    past_key_values=cache,
                    use_cache=True,
                    logits_to_keep=1,
                )
                if total > 4 * PREFILL_CHUNK:
                    yield Progress(f"Reading context ({_short(end)} of {_short(total)} tokens)")

    def _stream(self, model, processor, text: str, images: list, stop_ids: set[int], cancel: threading.Event, max_new_tokens: int, kv_cache: str | None = None) -> Iterator[str | Progress]:
        """Generate from `text` on a worker thread, yielding decoded pieces as they arrive."""
        from transformers import StoppingCriteria, StoppingCriteriaList, TextIteratorStreamer

        inputs = self.encode(processor, text, images)
        inputs = {k: v.to(model.device) if hasattr(v, "to") else v for k, v in inputs.items()}
        cache = make_cache(model.config, kv_cache)
        try:
            # Image prompts keep a single prefill: their rotary positions depend on image layout.
            if not images and inputs["input_ids"].shape[1] > PREFILL_CHUNK:
                yield from self._prefill(model, inputs["input_ids"], inputs.get("attention_mask"), cache, cancel)
                if cancel.is_set():
                    return
        except torch.OutOfMemoryError:
            cache = None
            torch.cuda.empty_cache()
            raise
        inputs["past_key_values"] = cache
        tokenizer = getattr(processor, "tokenizer", processor)
        streamer = TextIteratorStreamer(tokenizer, skip_prompt=True, skip_special_tokens=False)

        class _StopOnCancel(StoppingCriteria):
            def __call__(self, input_ids, scores, **kwargs):
                return torch.full((input_ids.shape[0],), cancel.is_set(), dtype=torch.bool, device=input_ids.device)

        agent_cfg = self.config.agent
        failure: list[BaseException] = []

        def run() -> None:
            try:
                with torch.inference_mode():
                    model.generate(
                        **inputs,
                        max_new_tokens=max_new_tokens,
                        do_sample=True,
                        temperature=agent_cfg.temperature,
                        top_p=agent_cfg.top_p,
                        top_k=agent_cfg.top_k,
                        eos_token_id=sorted(stop_ids) or None,
                        streamer=streamer,
                        stopping_criteria=StoppingCriteriaList([_StopOnCancel()]),
                    )
            except BaseException as e:  # noqa: BLE001 - re-raised in the consumer
                failure.append(e)
                streamer.end()

        worker = threading.Thread(target=run, name="localmind-generate", daemon=True)
        worker.start()
        finished = False
        try:
            for piece in streamer:
                yield piece
            finished = True
        finally:
            if not finished:
                cancel.set()  # the consumer went away: stop the GPU work too
            worker.join(timeout=30)
            inputs.pop("past_key_values", None)
            cache = None
        if failure:
            if isinstance(failure[0], torch.OutOfMemoryError):
                torch.cuda.empty_cache()
            raise failure[0]


def _other_processes_vram() -> float:
    """VRAM used by everything except this process (desktop, browser, other apps)."""
    try:
        from localmind.metrics import gpu_stats

        stats = gpu_stats()
        if stats:
            return max(0.0, stats.used_gb * GIB - torch.cuda.memory_reserved())
    except Exception:  # noqa: BLE001
        pass
    return 1.0 * GIB


def _available_ram() -> float:
    try:
        import psutil

        return float(psutil.virtual_memory().available)
    except ImportError:
        return 8.0 * GIB
