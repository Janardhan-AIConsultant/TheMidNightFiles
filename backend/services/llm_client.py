"""Injectable LLM client protocol, OpenAI/OpenRouter implementations (langchain-openai) and a scripted fake for tests."""
from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol, runtime_checkable

from backend.config import Settings, get_settings
from backend.services.model_registry import ModelRegistry, ModelSpec

log = logging.getLogger("midnight.agent.llm")


class LLMError(Exception):
    """Base class for provider failures."""


class LLMRateLimitError(LLMError):
    pass


class LLMTimeoutError(LLMError):
    pass


class LLMModelError(LLMError):
    pass


@dataclass
class LLMRequest:
    agent_id: str
    model: str
    system: str
    user: str
    max_output_tokens: int = 1024
    timeout: float = 120.0
    json_output: bool = True
    metadata: dict = field(default_factory=dict)


@dataclass
class LLMResponse:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = ""


@runtime_checkable
class LLMClient(Protocol):
    def invoke(self, request: LLMRequest) -> LLMResponse: ...


class OpenAILLMClient:
    """OpenAI chat model via langchain-openai. Constructed lazily so imports never require a key."""

    def __init__(self, settings: Settings | None = None, temperature: float = 0.7):
        self.settings = settings or get_settings()
        self.temperature = temperature
        self._models: dict[tuple, Any] = {}
        self._lock = threading.Lock()

    # Provider hooks (overridden by OpenRouterLLMClient)
    def _api_key(self) -> str | None:
        return self.settings.openai_api_key.get_secret_value() or None

    def _extra_kwargs(self) -> dict[str, Any]:
        return {}

    def _model(self, req: LLMRequest):
        key = (req.model, req.max_output_tokens, req.timeout, req.json_output)
        with self._lock:
            if key not in self._models:
                from langchain_openai import ChatOpenAI
                kwargs: dict[str, Any] = {}
                if req.json_output:
                    kwargs["model_kwargs"] = {"response_format": {"type": "json_object"}}
                self._models[key] = ChatOpenAI(
                    model=req.model, api_key=self._api_key(),
                    temperature=self.temperature, max_tokens=req.max_output_tokens, timeout=req.timeout,
                    max_retries=0, **self._extra_kwargs(), **kwargs)
            return self._models[key]

    def invoke(self, req: LLMRequest) -> LLMResponse:
        try:
            msg = self._model(req).invoke([("system", req.system), ("human", req.user)])
        except Exception as exc:  # map provider exceptions to the structured taxonomy
            name = type(exc).__name__
            if "RateLimit" in name:
                raise LLMRateLimitError(str(exc)) from exc
            if "Timeout" in name:
                raise LLMTimeoutError(str(exc)) from exc
            raise LLMModelError(f"{name}: {exc}") from exc
        usage = getattr(msg, "usage_metadata", None) or {}
        content = msg.content if isinstance(msg.content, str) else json.dumps(msg.content)
        return LLMResponse(text=content, input_tokens=int(usage.get("input_tokens", 0)),
                           output_tokens=int(usage.get("output_tokens", 0)), model=req.model)


class OpenRouterLLMClient(OpenAILLMClient):
    """OpenRouter via its OpenAI-compatible API. Pilot: only ':free' models unless OPENROUTER_ALLOW_PAID=true.

    Free models are heavily rate limited (HTTP 429 -> LLMRateLimitError) and not all honour JSON mode; the
    orchestrator's existing retry/parse handling applies unchanged."""

    def _api_key(self) -> str | None:
        return self.settings.openrouter_api_key.get_secret_value() or None

    def _extra_kwargs(self) -> dict[str, Any]:
        headers = {"X-Title": self.settings.openrouter_app_name}
        if self.settings.openrouter_site_url:
            headers["HTTP-Referer"] = self.settings.openrouter_site_url
        return {"base_url": self.settings.openrouter_base_url, "default_headers": headers}

    def invoke(self, req: LLMRequest) -> LLMResponse:
        if not self.settings.openrouter_allow_paid and not req.model.endswith(":free"):
            raise LLMModelError(f"model {req.model!r} is not a ':free' OpenRouter model "
                                "(set OPENROUTER_ALLOW_PAID=true to allow paid models)")
        return super().invoke(req)


class FakeLLMClient:
    """Scripted client. ``responses[agent_id]`` may be a dict/str, an Exception, a callable(request), or a list of
    these (consumed in order; the last item repeats)."""

    def __init__(self, responses: dict[str, Any] | None = None, default: Any = None):
        self.responses: dict[str, Any] = dict(responses or {})
        self.default = default
        self.calls: list[LLMRequest] = []
        self._idx: dict[str, int] = {}
        self._lock = threading.Lock()

    def set(self, agent_id: str, response: Any) -> None:
        with self._lock:
            self.responses[agent_id] = response
            self._idx.pop(agent_id, None)

    def calls_for(self, agent_id: str) -> list[LLMRequest]:
        return [c for c in self.calls if c.agent_id == agent_id]

    def invoke(self, request: LLMRequest) -> LLMResponse:
        with self._lock:
            self.calls.append(request)
            item = self.responses.get(request.agent_id, self.default)
            if isinstance(item, list):
                i = self._idx.get(request.agent_id, 0)
                self._idx[request.agent_id] = i + 1
                item = item[min(i, len(item) - 1)]
        if item is None:
            raise LLMModelError(f"FakeLLMClient has no response for {request.agent_id}")
        if callable(item) and not isinstance(item, (dict, str)):
            item = item(request)
        if isinstance(item, BaseException):
            raise item
        text = item if isinstance(item, str) else json.dumps(item)
        return LLMResponse(text=text, input_tokens=max(1, (len(request.system) + len(request.user)) // 4),
                           output_tokens=max(1, len(text) // 4), model=request.model)


# Documented public limits; anything else must be supplied through MODEL_REGISTRY_FILE (else conservative default).
_KNOWN = [
    ModelSpec("openai", "gpt-4o", 128_000, 16_384, tools=True, structured=True),
    ModelSpec("openai", "gpt-4o-mini", 128_000, 16_384, tools=True, structured=True),
    ModelSpec("openai", "gpt-4.1", 1_047_576, 32_768, tools=True, structured=True),
    # OpenRouter free pilot model (limits from OpenRouter's public /models listing)
    ModelSpec("openrouter", "google/gemma-4-31b-it:free", 262_144, 32_768, tools=True, structured=False),
]


def build_model_registry(settings: Settings | None = None) -> ModelRegistry:
    reg = ModelRegistry(settings or get_settings())
    for spec in _KNOWN:
        if not reg.known(spec.model_id):
            reg.register(spec)
    return reg


def build_llm_client(settings: Settings | None = None) -> LLMClient:
    s = settings or get_settings()
    provider = s.llm_provider.lower()
    if provider == "openai":
        return OpenAILLMClient(s)
    if provider == "openrouter":
        return OpenRouterLLMClient(s)
    raise ValueError(f"unsupported LLM_PROVIDER {s.llm_provider!r}")
