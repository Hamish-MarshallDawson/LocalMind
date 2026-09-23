from __future__ import annotations

import json
import threading
import logging
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger(__name__)


@dataclass
class ToolDefinition:
    name: str
    description: str
    parameters: dict[str, Any]
    function: Callable
    required_params: list[str] = field(default_factory=list)

    def to_schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": self.parameters,
                    "required": self.required_params,
                },
            },
        }


def _coerce(value: Any, kind: str | None) -> Any:
    """Models send `"5"` for integers and `"true"` for booleans often enough to matter."""
    if value is None or kind is None:
        return value
    if kind == "integer":
        return int(float(value))
    if kind == "number":
        return float(value)
    if kind == "boolean":
        if isinstance(value, str):
            return value.strip().lower() in {"true", "1", "yes", "y"}
        return bool(value)
    if kind == "string" and not isinstance(value, str):
        return json.dumps(value) if isinstance(value, (dict, list)) else str(value)
    return value


def _conform(tool: ToolDefinition, arguments: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Drop parameters the tool doesn't declare and coerce the rest to their schema types."""
    cleaned: dict[str, Any] = {}
    problems: list[str] = []
    for key, value in arguments.items():
        spec = tool.parameters.get(key)
        if spec is None:
            logger.info("Ignoring unexpected argument %r for tool %s", key, tool.name)
            continue
        try:
            cleaned[key] = _coerce(value, spec.get("type"))
        except (TypeError, ValueError):
            problems.append(f"{key} should be {spec.get('type')}, got {value!r}")
    for required in tool.required_params:
        if cleaned.get(required) in (None, ""):
            problems.append(f"missing required argument {required!r}")
    return cleaned, problems


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, ToolDefinition] = {}
        # MCP servers add and remove tools from their own thread while turns read the list.
        self._lock = threading.Lock()

    def register(
        self,
        name: str,
        description: str,
        parameters: dict[str, Any],
        function: Callable,
        required_params: list[str] | None = None,
    ) -> None:
        definition = ToolDefinition(
            name=name,
            description=description,
            parameters=parameters,
            function=function,
            required_params=required_params or [],
        )
        with self._lock:
            self._tools[name] = definition
        logger.debug("Registered tool: %s", name)

    def unregister(self, name: str) -> bool:
        with self._lock:
            return self._tools.pop(name, None) is not None

    def get(self, name: str) -> ToolDefinition | None:
        with self._lock:
            return self._tools.get(name)

    def list_tools(self) -> list[str]:
        with self._lock:
            return list(self._tools.keys())

    def get_schemas(self) -> list[dict]:
        with self._lock:
            tools = list(self._tools.values())
        return [tool.to_schema() for tool in tools]

    def execute(self, name: str, arguments: dict[str, Any]) -> str:
        tool = self.get(name)
        if tool is None:
            return json.dumps({"error": f"Unknown tool: {name}", "available": self.list_tools()})
        if not isinstance(arguments, dict):
            return json.dumps({"error": f"Arguments for {name} must be a JSON object"})

        arguments, problems = _conform(tool, arguments)
        if problems:
            return json.dumps({"error": f"Bad arguments for {name}: " + "; ".join(problems)})
        try:
            result = tool.function(**arguments)
            if isinstance(result, str):
                return result
            return json.dumps(result, default=str)
        except Exception as e:
            logger.error("Tool %s failed: %s", name, e)
            return json.dumps({"error": str(e)})
