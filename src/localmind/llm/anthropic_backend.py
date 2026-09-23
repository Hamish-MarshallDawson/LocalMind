"""Claude via the Anthropic Messages API.

Transcript rules this backend relies on (see the Claude API docs on preserved thinking):
- Within one turn, an assistant message that called tools is replayed with its original content
  blocks (thinking included) - the API needs them to continue a tool loop.
- Earlier turns are sent without thinking blocks. Dropping the oldest thinking blocks is always
  valid, and it means trimming old history for the context budget can never invalidate anything.
"""
from __future__ import annotations

import base64
import io
import json
import logging
import os
import threading
from collections.abc import Iterator
from pathlib import Path

from .types import Chunk, ModelSpec, RoundResult, ToolCall

logger = logging.getLogger(__name__)

FALLBACK_BETA = "server-side-fallback-2026-07-01"
THINKING_BUDGET = 8000  # Haiku 4.5 only; newer models use adaptive thinking


class ClaudeNotConfigured(RuntimeError):
    pass


def credentials_hint() -> str | None:
    """None when some credential source exists; otherwise how to set one up."""
    if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        return None
    config_dir = os.environ.get("ANTHROPIC_CONFIG_DIR")
    candidates = [Path(config_dir)] if config_dir else []
    if os.environ.get("APPDATA"):
        candidates.append(Path(os.environ["APPDATA"]) / "Anthropic")
    candidates.append(Path.home() / ".config" / "anthropic")
    if any((c / "credentials").is_dir() and any((c / "credentials").iterdir()) for c in candidates if c.exists()):
        return None
    return "Sign in with `ant auth login` (or set ANTHROPIC_API_KEY), then restart LocalMind."


class AnthropicBackend:
    def __init__(self, spec: ModelSpec, config, client_factory=None):
        self.spec = spec
        self.config = config
        self._client_factory = client_factory
        self._client = None

    @property
    def client(self):
        if self._client is None:
            if self._client_factory is not None:
                self._client = self._client_factory()
            else:
                import anthropic

                self._client = anthropic.Anthropic()
        return self._client

    def load_notice(self, thinking: bool) -> str | None:
        return None

    def context_window(self, kv_cache: str | None = None) -> int:
        return self.spec.context_window  # server-side; KV cache type doesn't apply

    # ------------------------------------------------------------------ request building
    def _thinking_param(self, thinking: bool) -> dict | None:
        mode = self.spec.thinking
        if mode == "always":
            return {"type": "adaptive", "display": "summarized"}
        if mode == "native":
            return {"type": "adaptive", "display": "summarized"} if thinking else {"type": "disabled"}
        if mode == "budget" and thinking:
            return {"type": "enabled", "budget_tokens": THINKING_BUDGET}
        return None

    @staticmethod
    def _tools(tools: list[dict] | None) -> list[dict]:
        out = []
        for tool in tools or []:
            fn = tool.get("function", tool)
            out.append({
                "name": fn["name"],
                "description": fn.get("description", ""),
                "input_schema": fn.get("parameters") or {"type": "object", "properties": {}},
                # Stream tool inputs as generated; the registry validates and coerces them.
                "eager_input_streaming": True,
            })
        return out

    def _user_content(self, content) -> str | list[dict]:
        if isinstance(content, str):
            return content
        blocks = []
        for part in content or []:
            if not isinstance(part, dict):
                continue
            if part.get("type") == "image" and part.get("image") is not None:
                buffer = io.BytesIO()
                part["image"].convert("RGB").save(buffer, format="JPEG", quality=90)
                blocks.append({
                    "type": "image",
                    "source": {"type": "base64", "media_type": "image/jpeg", "data": base64.standard_b64encode(buffer.getvalue()).decode()},
                })
            elif part.get("type") == "text" and part.get("text"):
                blocks.append({"type": "text", "text": part["text"]})
        return blocks or "(empty message)"

    def convert(self, messages: list[dict]) -> tuple[str, list[dict]]:
        system_parts: list[str] = []
        out: list[dict] = []
        results: list[dict] = []

        def flush_results():
            if results:
                out.append({"role": "user", "content": list(results)})
                results.clear()

        for message in messages:
            role = message.get("role")
            if role == "system":
                system_parts.append(str(message.get("content", "")))
                continue
            if role == "tool":
                results.append({
                    "type": "tool_result",
                    "tool_use_id": message.get("tool_call_id") or "missing",
                    "content": str(message.get("content", "")),
                })
                continue
            flush_results()
            if role == "assistant":
                provider = message.get("_provider")
                if provider and provider[0] == self.spec.model:
                    out.append({"role": "assistant", "content": provider[1]})
                    continue
                blocks = []
                text = message.get("content")
                if isinstance(text, str) and text.strip():
                    blocks.append({"type": "text", "text": text})
                for call in message.get("tool_calls") or []:
                    fn = call.get("function", {})
                    blocks.append({"type": "tool_use", "id": call.get("id"), "name": fn.get("name"), "input": fn.get("arguments") or {}})
                if blocks:
                    out.append({"role": "assistant", "content": blocks})
            else:
                out.append({"role": "user", "content": self._user_content(message.get("content"))})
        flush_results()
        return "\n\n".join(p for p in system_parts if p), out

    def _request(self, messages, tools, thinking, force_tool) -> tuple[object, dict]:
        system, converted = self.convert(messages)
        kwargs: dict = {
            "model": self.spec.model,
            "max_tokens": self.spec.max_output_tokens,
            "messages": converted,
            "cache_control": {"type": "ephemeral"},
        }
        if system:
            kwargs["system"] = system
        if tools:
            kwargs["tools"] = self._tools(tools)
            if force_tool and self.spec.forced_tools:
                kwargs["tool_choice"] = {"type": "tool", "name": force_tool}
        thinking_param = self._thinking_param(thinking)
        if thinking_param:
            kwargs["thinking"] = thinking_param
        if self.spec.server_fallbacks:
            return self.client.beta.messages, {**kwargs, "betas": [FALLBACK_BETA], "fallbacks": "default"}
        return self.client.messages, kwargs

    # ------------------------------------------------------------------ calls
    def count_tokens(self, messages: list[dict], tools: list[dict] | None, thinking: bool) -> tuple[int, bool]:
        try:
            system, converted = self.convert(messages)
            kwargs = {"model": self.spec.model, "messages": converted}
            if system:
                kwargs["system"] = system
            if tools:
                kwargs["tools"] = [{k: v for k, v in t.items() if k != "eager_input_streaming"} for t in self._tools(tools)]
            return int(self.client.messages.count_tokens(**kwargs).input_tokens), True
        except Exception as e:  # noqa: BLE001 - offline or signed out: estimate instead
            logger.debug("count_tokens unavailable (%s); estimating", e)
            size = sum(len(json.dumps(m.get("content"), default=str)) for m in messages)
            return size // 4, False

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
        hint = credentials_hint() if self._client_factory is None else None
        if hint:
            raise ClaudeNotConfigured(f"Claude isn't connected. {hint}")

        api, kwargs = self._request(messages, tools, thinking, force_tool)
        thinking_text, text = "", ""
        final = None
        for attempt in range(3):
            thinking_text, text = "", ""
            try:
                with api.stream(**kwargs) as stream:
                    for event in stream:
                        if cancel.is_set():
                            break
                        kind = getattr(event, "type", "")
                        if kind == "content_block_start" and getattr(event.content_block, "type", "") == "tool_use":
                            yield Chunk("calling")
                        elif kind == "content_block_delta":
                            delta = event.delta
                            if delta.type == "thinking_delta":
                                thinking_text += delta.thinking
                                yield Chunk("thinking", thinking_text)
                            elif delta.type == "text_delta":
                                text += delta.text
                                yield Chunk("text", text)
                    else:
                        final = stream.get_final_message()
                break
            except ValueError:
                # With eager tool-input streaming, JSON the SDK cannot parse at all surfaces as a
                # ValueError from the stream. There is no tool_use id to answer, so re-issue the
                # round. API errors are not ValueError and propagate.
                if attempt == 2:
                    raise
                logger.warning("Unparseable streamed tool input from Claude; retrying the round")
                yield Chunk("text", "")

        if final is None:  # cancelled mid-stream
            yield RoundResult(text=text, thinking=thinking_text or None, tool_calls=[], stop_reason="cancelled")
            return

        notice = None
        blocks = list(final.content)
        for block in blocks:
            if getattr(block, "type", "") == "fallback":
                notice = f"{block.from_.model} declined, so {block.to.model} answered this turn."
        calls = [ToolCall(id=b.id, name=b.name, arguments=b.input if isinstance(b.input, dict) else {}) for b in blocks if getattr(b, "type", "") == "tool_use"]
        stop = final.stop_reason
        if stop == "refusal":
            category = getattr(getattr(final, "stop_details", None), "category", None)
            notice = f"Claude declined this request{f' ({category})' if category else ''}."
            calls = []
        elif stop == "max_tokens" and calls:
            notice = "The reply hit the output limit mid tool call, so the call was not run."
            calls = []

        usage = final.usage
        context = sum(int(getattr(usage, f, 0) or 0) for f in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens", "output_tokens"))
        final_text = "".join(getattr(b, "text", "") for b in blocks if getattr(b, "type", "") == "text")
        final_thinking = "".join(getattr(b, "thinking", "") or "" for b in blocks if getattr(b, "type", "") == "thinking")
        yield RoundResult(
            text=final_text.strip(),
            thinking=final_thinking.strip() or thinking_text.strip() or None,
            tool_calls=calls,
            context_tokens=context or None,
            provider_payload=(self.spec.model, blocks) if calls else None,
            stop_reason=stop,
            notice=notice,
        )
