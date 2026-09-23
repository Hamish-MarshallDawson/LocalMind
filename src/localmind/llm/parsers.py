"""Turn raw local-model output into reasoning, visible text and tool calls.

Each model family writes tool calls and reasoning in its own markup. A parser knows one family's
markup, plus how to *prefill* a tool call so a forced tool is guaranteed to be called.
"""
from __future__ import annotations

import json
import logging
import re

from .types import ToolCall

logger = logging.getLogger(__name__)


class OutputParser:
    family = ""
    stop_tokens: tuple[str, ...] = ()
    thinking_open = ""  # text that starts a reasoning block
    thinking_close_token = ""  # single token that ends one (used as a stop token)

    # -- reasoning -----------------------------------------------------------------------------
    def prompt_opens_thinking(self, prompt: str) -> bool:
        raise NotImplementedError

    def close_thinking(self) -> str:
        raise NotImplementedError

    def split_thinking(self, text: str, opens: bool, partial: bool) -> tuple[str | None, str]:
        raise NotImplementedError

    # -- tool calls ----------------------------------------------------------------------------
    def forced_call_prefix(self, tool: str, first_param: str) -> str:
        raise NotImplementedError

    def tool_calls(self, body: str) -> list[ToolCall]:
        raise NotImplementedError

    def visible_partial(self, body: str) -> tuple[str, bool]:
        raise NotImplementedError

    def clean(self, body: str) -> str:
        raise NotImplementedError

    @staticmethod
    def _hold_back_partial_tag(body: str) -> str:
        """Don't flash half a control tag ("<tool_ca", "<|im_e") while tokens stream."""
        lt = body.rfind("<")
        if lt != -1 and ">" not in body[lt:] and len(body) - lt <= 16:
            return body[:lt]
        return body


# ---------------------------------------------------------------------------------------------
class QwenParser(OutputParser):
    """Qwen2.5 / Qwen3 / Qwen3-VL: <think>…</think> and <tool_call>{json}</tool_call>."""

    family = "qwen"
    stop_tokens = ("<|im_end|>",)
    thinking_open = "<think>\n"
    thinking_close_token = "</think>"

    def prompt_opens_thinking(self, prompt: str) -> bool:
        return prompt.rstrip().endswith("<think>")

    def close_thinking(self) -> str:
        return "\n</think>\n\n"

    def split_thinking(self, text: str, opens: bool, partial: bool) -> tuple[str | None, str]:
        if "</think>" in text:
            head, _, body = text.partition("</think>")
            return head.replace("<think>", "").strip() or None, body
        if opens or text.lstrip().startswith("<think>"):
            # Still reasoning (or reasoning never closed before the token limit): no reply yet.
            return text.replace("<think>", "").strip() or None, ""
        return None, text

    def forced_call_prefix(self, tool: str, first_param: str) -> str:
        return f'<tool_call>\n{{"name": "{tool}", "arguments": {{"{first_param}": "'

    def tool_calls(self, body: str) -> list[ToolCall]:
        calls = []
        for part in body.split("<tool_call>")[1:]:
            end = part.find("</tool_call>")
            raw = (part if end == -1 else part[:end]).strip()
            if end == -1 and not raw.endswith("}"):
                continue
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                logger.warning("Unparseable Qwen tool call: %s", raw[:200])
                continue
            if isinstance(data, dict) and data.get("name"):
                args = data.get("arguments") or {}
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {}
                calls.append(ToolCall(name=data["name"], arguments=args if isinstance(args, dict) else {}))
        return calls

    def visible_partial(self, body: str) -> tuple[str, bool]:
        idx = body.find("<tool_call>")
        if idx != -1:
            return self.clean(body[:idx]), True
        return self.clean(self._hold_back_partial_tag(body)), False

    def clean(self, body: str) -> str:
        body = re.sub(r"<think>.*?</think>", "", body, flags=re.DOTALL)
        body = re.sub(r"<\|im_end\|>|<\|endoftext\|>|<\|im_start\|>", "", body)
        return body.strip()


# ---------------------------------------------------------------------------------------------
class Gemma4Parser(OutputParser):
    """Gemma 4: <|channel>thought…<channel|> and <|tool_call>call:name{key:<|"|>v<|"|>}<tool_call|>."""

    family = "gemma4"
    stop_tokens = ("<turn|>", "<|tool_response>")
    QUOTE = '<|"|>'
    THOUGHT_OPEN = "<|channel>thought\n"
    thinking_open = THOUGHT_OPEN
    thinking_close_token = "<channel|>"

    def prompt_opens_thinking(self, prompt: str) -> bool:
        return prompt.endswith(self.THOUGHT_OPEN)

    def close_thinking(self) -> str:
        return "<channel|>"

    def split_thinking(self, text: str, opens: bool, partial: bool) -> tuple[str | None, str]:
        if opens and not text.startswith("<|channel>"):
            text = self.THOUGHT_OPEN + text
        if "<|channel>" not in text:
            return None, text
        thoughts, body, rest = [], [], text
        while "<|channel>" in rest:
            before, _, after = rest.partition("<|channel>")
            body.append(before)
            if "<channel|>" not in after:
                thoughts.append(after)  # still thinking
                rest = ""
                break
            thought, _, rest = after.partition("<channel|>")
            thoughts.append(thought)
        body.append(rest)
        thinking = "\n".join(t.removeprefix("thought").strip() for t in thoughts).strip()
        return thinking or None, "".join(body)

    def forced_call_prefix(self, tool: str, first_param: str) -> str:
        return f"<|tool_call>call:{tool}{{{first_param}:{self.QUOTE}"

    def tool_calls(self, body: str) -> list[ToolCall]:
        calls = []
        for match in re.finditer(r"<\|tool_call>call:([\w.-]+)", body):
            start = match.end()
            try:
                args, _ = _GemmaArgs(body, start, self.QUOTE).parse_object()
            except ValueError as e:
                logger.warning("Unparseable Gemma tool call %s: %s", match.group(1), e)
                continue
            calls.append(ToolCall(name=match.group(1), arguments=args))
        return calls

    def visible_partial(self, body: str) -> tuple[str, bool]:
        idx = body.find("<|tool_call>")
        if idx != -1:
            return self.clean(body[:idx]), True
        return self.clean(self._hold_back_partial_tag(body)), False

    def clean(self, body: str) -> str:
        body = re.sub(r"<\|channel>.*?<channel\|>", "", body, flags=re.DOTALL)
        body = re.sub(r"<turn\|>|<\|tool_response>|<eos>|<bos>|<\|turn>model", "", body)
        return body.strip()


class _GemmaArgs:
    """Recursive-descent reader for Gemma's argument syntax: {key:<|"|>text<|"|>,n:5,list:[…]}."""

    def __init__(self, text: str, pos: int, quote: str):
        self.text, self.pos, self.quote = text, pos, quote

    def _skip(self) -> None:
        while self.pos < len(self.text) and self.text[self.pos] in " \n\t\r":
            self.pos += 1

    def _expect(self, ch: str) -> None:
        self._skip()
        if not self.text.startswith(ch, self.pos):
            raise ValueError(f"expected {ch!r} at {self.pos}")
        self.pos += len(ch)

    def parse_object(self) -> tuple[dict, int]:
        self._expect("{")
        out: dict = {}
        self._skip()
        if self.text.startswith("}", self.pos):
            self.pos += 1
            return out, self.pos
        while True:
            key = self._key()
            self._expect(":")
            out[key] = self._value()
            self._skip()
            if self.text.startswith(",", self.pos):
                self.pos += 1
                continue
            self._expect("}")
            return out, self.pos

    def _key(self) -> str:
        self._skip()
        if self.text.startswith(self.quote, self.pos):
            return self._string()
        end = self.text.find(":", self.pos)
        if end == -1:
            raise ValueError("key without ':'")
        key = self.text[self.pos:end].strip()
        self.pos = end
        return key

    def _string(self) -> str:
        self.pos += len(self.quote)
        end = self.text.find(self.quote, self.pos)
        if end == -1:
            raise ValueError("unterminated string")
        value = self.text[self.pos:end]
        self.pos = end + len(self.quote)
        return value

    def _value(self):
        self._skip()
        text = self.text
        if text.startswith(self.quote, self.pos):
            return self._string()
        if text.startswith("{", self.pos):
            value, _ = self.parse_object()
            return value
        if text.startswith("[", self.pos):
            self.pos += 1
            items = []
            self._skip()
            if text.startswith("]", self.pos):
                self.pos += 1
                return items
            while True:
                items.append(self._value())
                self._skip()
                if text.startswith(",", self.pos):
                    self.pos += 1
                    continue
                self._expect("]")
                return items
        match = re.compile(r"[^,}\]]+").match(text, self.pos)
        if not match:
            raise ValueError(f"empty value at {self.pos}")
        self.pos = match.end()
        raw = match.group(0).strip()
        if raw in ("true", "false"):
            return raw == "true"
        if raw == "null":
            return None
        try:
            return int(raw)
        except ValueError:
            try:
                return float(raw)
            except ValueError:
                return raw


PARSERS: dict[str, type[OutputParser]] = {"qwen": QwenParser, "gemma4": Gemma4Parser}


def parser_for(family: str) -> OutputParser:
    try:
        return PARSERS[family]()
    except KeyError as e:
        raise ValueError(f"No output parser for model family {family!r}") from e
