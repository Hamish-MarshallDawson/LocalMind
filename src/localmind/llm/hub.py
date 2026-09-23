"""The set of chat models the user can pick from, and one backend instance per model."""
from __future__ import annotations

from .types import ModelSpec


class ModelHub:
    def __init__(self, config, model_manager, anthropic_client_factory=None):
        self.config = config
        self.model_manager = model_manager
        self.anthropic_client_factory = anthropic_client_factory
        self.specs: dict[str, ModelSpec] = {}
        for option in config.chat_models.options:
            data = option.model_dump()
            if data.get("evidence_check") is None:
                # Local models benefit from a nudge to use tools; Claude uses them well unprompted,
                # and every nudge would be a second paid request.
                data["evidence_check"] = data["provider"] == "local"
            self.specs[option.key] = ModelSpec(**data)
        self.default_key = config.chat_models.default if config.chat_models.default in self.specs else next(iter(self.specs))
        self._backends: dict[str, object] = {}

    def spec(self, key: str | None) -> ModelSpec:
        return self.specs.get(key or "", self.specs[self.default_key])

    def backend(self, key: str | None):
        spec = self.spec(key)
        if spec.key not in self._backends:
            if spec.provider == "anthropic":
                from .anthropic_backend import AnthropicBackend

                self._backends[spec.key] = AnthropicBackend(spec, self.config, self.anthropic_client_factory)
            else:
                from .local import LocalBackend

                self._backends[spec.key] = LocalBackend(spec, self.model_manager, self.config)
        return self._backends[spec.key]

    def forget_windows(self) -> None:
        """Make local models re-measure their context windows, after VRAM use changed under them."""
        for backend in self._backends.values():
            if hasattr(backend, "forget_windows"):
                backend.forget_windows()

    def choices(self) -> list[tuple[str, str]]:
        return [(spec.label, spec.key) for spec in self.specs.values()]
