"""Provider-neutral types shared by every chat backend.

Conversations are stored in one neutral shape that both the Hugging Face chat templates and the
Anthropic adapter understand:

    {"role": "system" | "user" | "assistant" | "tool", "content": str | list[part]}
    assistant messages may carry  "tool_calls": [{"id", "type": "function", "function": {"name", "arguments": dict}}]
    tool messages carry           "tool_call_id" and "name"

Keys starting with "_" are in-memory only (e.g. provider-native content needed to continue a
tool loop) and are never persisted.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Literal

Provider = Literal["local", "anthropic"]
ThinkingMode = Literal["none", "native", "variant", "always", "budget"]


@dataclass(frozen=True)
class ModelSpec:
    key: str
    label: str
    provider: Provider
    model: str  # HF repo id or Anthropic model id
    family: str = ""  # parser family for local models: "qwen" | "gemma4"
    thinking: ThinkingMode = "none"
    thinking_model: str | None = None  # for thinking == "variant": a separate checkpoint
    vision: bool = False
    context_window: int = 32768
    max_output_tokens: int = 8192
    forced_tools: bool = True  # False: the model rejects forced tool_choice; tools are pre-run instead
    evidence_check: bool = True  # challenge tool-free answers once
    server_fallbacks: bool = False  # Anthropic server-side refusal fallbacks
    weights_gb: float = 0.0  # VRAM the 4-bit weights occupy; sizes the local context window
    kv_cache: str | None = None  # preferred KV cache type for new chats; None = global default
    attention_transient_kb: float = 16.0  # measured per-token VRAM attention needs beyond the KV cache
    note: str = ""

    @property
    def is_cloud(self) -> bool:
        return self.provider != "local"

    @property
    def can_toggle_thinking(self) -> bool:
        return self.thinking in ("native", "variant", "budget")


@dataclass
class ToolCall:
    name: str
    arguments: dict
    id: str = field(default_factory=lambda: f"call_{uuid.uuid4().hex[:16]}")

    def as_message_part(self) -> dict:
        return {"id": self.id, "type": "function", "function": {"name": self.name, "arguments": self.arguments}}


@dataclass
class Chunk:
    """A streaming update. `text` is cumulative for its kind, not a delta."""

    kind: Literal["thinking", "text", "calling", "status"]
    text: str = ""


@dataclass
class RoundResult:
    text: str
    thinking: str | None
    tool_calls: list[ToolCall]
    context_tokens: int | None = None  # prompt + output size after this round, when the backend knows it
    provider_payload: object = None  # e.g. Anthropic content blocks, replayed within the same turn
    stop_reason: str | None = None
    notice: str | None = None  # something the user should see (fallback model used, refusal, ...)
