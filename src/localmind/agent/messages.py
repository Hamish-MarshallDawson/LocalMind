"""Transcript normalisation.

Chats saved before multi-model support stored tool calls as raw Qwen markup inside assistant text
and tool results without a tool_call_id. Gemma's template and the Anthropic API both need the
structured form, so old transcripts are upgraded when they are opened.
"""
from __future__ import annotations

from localmind.llm.parsers import QwenParser

_qwen = QwenParser()


def normalize_transcript(messages: list[dict]) -> list[dict]:
    out: list[dict] = []
    open_calls: list[dict] = []  # tool calls from the latest assistant message awaiting results

    for original in messages or []:
        message = dict(original)
        role = message.get("role")

        if role == "assistant":
            content = message.get("content")
            if isinstance(content, str) and "<tool_call>" in content and not message.get("tool_calls"):
                calls = _qwen.tool_calls(content)
                message["content"] = _qwen.visible_partial(content)[0]
                message["tool_calls"] = [c.as_message_part() for c in calls]
            open_calls = list(message.get("tool_calls") or [])
            out.append(message)
            continue

        if role == "tool":
            if not message.get("tool_call_id"):
                match = next((c for c in open_calls if c["function"]["name"] == message.get("name")), None)
                match = match or (open_calls[0] if open_calls else None)
                if match is None:
                    # A result with no call to belong to: keep the evidence as plain context.
                    out.append({"role": "user", "content": f"[Earlier {message.get('name', 'tool')} result]\n{message.get('content', '')}"})
                    continue
                message["tool_call_id"] = match["id"]
                message.setdefault("name", match["function"]["name"])
            open_calls = [c for c in open_calls if c["id"] != message["tool_call_id"]]
            out.append(message)
            continue

        open_calls = []
        out.append(message)

    return out
