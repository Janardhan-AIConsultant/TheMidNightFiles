"""Model capability registry.

No context limits or prices are invented here. The registry ships EMPTY of verified models:
operators register verified specs via ``register()`` or a JSON file (MODEL_REGISTRY_FILE:
a list of objects with the ModelSpec fields). Unknown models get a CONSERVATIVE DEFAULT
(ASSUMPTION): context_limit=DEFAULT_CONTEXT_LIMIT (8192), max_output=DEFAULT_MAX_OUTPUT (2048),
no tool or structured-output support, no pricing. Real models will usually allow much more;
the default only guarantees we never overrun an unknown model.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from backend.config import Settings, get_settings


@dataclass(frozen=True)
class ModelSpec:
    provider: str
    model_id: str
    context_limit: int
    max_output: int
    tools: bool = False
    structured: bool = False
    pricing: dict | None = None  # only where verified, e.g. {"input_per_1m": x, "output_per_1m": y}
    verified: bool = True        # False for the fallback default


class ModelRegistry:
    def __init__(self, settings: Settings | None = None, specs: list[ModelSpec] | None = None):
        self.settings = settings or get_settings()
        self._specs: dict[str, ModelSpec] = {}
        for s in specs or []:
            self.register(s)
        if self.settings.model_registry_file:
            self.load_file(self.settings.model_registry_file)

    def register(self, spec: ModelSpec) -> None:
        if spec.context_limit <= 0 or spec.max_output <= 0 or spec.max_output >= spec.context_limit:
            raise ValueError(f"invalid limits for model {spec.model_id}")
        self._specs[spec.model_id] = spec

    def load_file(self, path: str | Path) -> int:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        for d in data:
            self.register(ModelSpec(**d))
        return len(data)

    def default_spec(self, model_id: str = "unknown") -> ModelSpec:
        return ModelSpec(provider="unknown", model_id=model_id or "unknown",
                         context_limit=self.settings.default_context_limit,
                         max_output=self.settings.default_max_output, tools=False, structured=False,
                         pricing=None, verified=False)

    def get(self, model_id: str) -> ModelSpec:
        return self._specs.get(model_id) or self.default_spec(model_id)

    def known(self, model_id: str) -> bool:
        return model_id in self._specs

    def all(self) -> list[ModelSpec]:
        return list(self._specs.values())
