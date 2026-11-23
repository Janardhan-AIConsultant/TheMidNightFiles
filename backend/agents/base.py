"""BaseAgent: Pydantic in/out, versioned prompt, context budget, timeout, bounded retries, cache, fail-open tracing,
restricted tools, structured errors. A failed run NEVER yields an approving output."""
from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, ClassVar, Optional

from pydantic import BaseModel, ValidationError

from backend.agents.schemas import AgentInput, AgentOutput
from backend.agents.tracing import trace_span
from backend.services.cache_service import CacheService
from backend.services.context_budget_service import ContextBudgetService, ContextOverflowError
from backend.services.llm_client import (LLMClient, LLMModelError, LLMRateLimitError, LLMRequest, LLMTimeoutError)

log = logging.getLogger("midnight.agent")

PROMPT_DIR = Path(__file__).resolve().parents[2] / "prompts"


class ErrorKind(str, Enum):
    VALIDATION = "validation"
    CONTEXT_OVERFLOW = "context_overflow"
    RATE_LIMIT = "rate_limit"
    MODEL = "model"
    TIMEOUT = "timeout"
    TOOL = "tool"
    CACHE = "cache"
    WORKFLOW = "workflow"
    PUBLISHING = "publishing"


class AgentError(BaseModel):
    kind: ErrorKind
    message: str
    agent_id: str = ""
    retryable: bool = False
    attempts: int = 0


class AgentFailure(Exception):
    def __init__(self, error: AgentError):
        super().__init__(f"{error.agent_id}: {error.kind.value}: {error.message}")
        self.error = error


class ToolPermissionError(PermissionError):
    pass


@dataclass
class AgentConfig:
    model_id: str = "gpt-4o"
    timeout_s: float = 120.0
    max_retries: int = 2          # extra attempts after the first
    backoff_base_s: float = 0.5
    max_tool_calls: int = 5
    use_cache: bool = True


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    calls: int = 0
    latency_ms: float = 0.0
    retries: int = 0

    def add(self, o: "Usage") -> None:
        self.input_tokens += o.input_tokens
        self.output_tokens += o.output_tokens
        self.calls += o.calls
        self.latency_ms += o.latency_ms
        self.retries += o.retries

    def as_dict(self) -> dict:
        return {"input_tokens": self.input_tokens, "output_tokens": self.output_tokens, "calls": self.calls,
                "latency_ms": round(self.latency_ms, 1), "retries": self.retries}


@dataclass
class AgentResult:
    agent_id: str
    ok: bool
    output: Optional[BaseModel] = None
    error: Optional[AgentError] = None
    usage: Usage = field(default_factory=Usage)
    cache_hit: bool = False
    prompt_version: str = ""
    model_id: str = ""
    attempts: int = 0
    context_utilisation: float = 0.0

    def unwrap(self) -> BaseModel:
        if not self.ok or self.output is None:
            raise AgentFailure(self.error or AgentError(kind=ErrorKind.WORKFLOW, message="no output",
                                                        agent_id=self.agent_id))
        return self.output


class PromptStore:
    """Loads prompts/<agent>/<version>.md; the content hash is part of cache keys and traces."""

    def __init__(self, root: Path | None = None):
        self.root = Path(root) if root else PROMPT_DIR

    def load(self, agent_id: str, version: str) -> tuple[str, str]:
        p = self.root / agent_id / f"{version}.md"
        text = p.read_text(encoding="utf-8")
        return text, hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.I)


def extract_json(text: str) -> Any:
    t = _FENCE.sub("", text.strip())
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        a, b = t.find("{"), t.rfind("}")
        if a >= 0 and b > a:
            return json.loads(t[a:b + 1])
        raise


class ToolBox:
    """Explicit tool permissions with a hard call bound. Anything not allow-listed is refused."""

    def __init__(self, agent_id: str, allowed: frozenset[str], tools: dict[str, Callable] | None, max_calls: int):
        self.agent_id, self.allowed, self.max_calls = agent_id, allowed, max_calls
        self._tools = dict(tools or {})
        self.calls = 0

    def has(self, name: str) -> bool:
        return name in self.allowed and name in self._tools

    def call(self, name: str, *args, **kwargs):
        if name not in self.allowed:
            raise ToolPermissionError(f"agent {self.agent_id} may not use tool {name!r}")
        if name not in self._tools:
            raise AgentFailure(AgentError(kind=ErrorKind.TOOL, message=f"tool {name!r} not provided",
                                          agent_id=self.agent_id))
        if self.calls >= self.max_calls:
            raise AgentFailure(AgentError(kind=ErrorKind.TOOL, message="tool call budget exhausted",
                                          agent_id=self.agent_id))
        self.calls += 1
        return self._tools[name](*args, **kwargs)


class BaseAgent:
    agent_id: ClassVar[str] = "base"
    input_model: ClassVar[type[AgentInput]] = AgentInput
    output_model: ClassVar[type[AgentOutput]] = AgentOutput
    prompt_version: ClassVar[str] = "v1"
    cache_namespace: ClassVar[Optional[str]] = None   # None = never cached
    allowed_tools: ClassVar[frozenset[str]] = frozenset()
    context_policy: ClassVar[str] = "none"            # documented, see subclasses
    uses_llm: ClassVar[bool] = True
    stop_conditions: ClassVar[str] = "valid output, or max_retries exhausted, or non-retryable error"

    def __init__(self, llm: LLMClient | None = None, budget: ContextBudgetService | None = None,
                 cache: CacheService | None = None, config: AgentConfig | None = None,
                 tools: dict[str, Callable] | None = None, prompts: PromptStore | None = None,
                 tracing: bool | None = None):
        self.llm, self.budget, self.cache = llm, budget, cache
        self.config = config or AgentConfig()
        self.prompts = prompts or PromptStore()
        self.tracing = tracing
        self.tools = ToolBox(self.agent_id, self.allowed_tools, tools, self.config.max_tool_calls)
        self._sleep = time.sleep
        self._tl = threading.local()  # per-run state: agents may be shared across worker threads

    def _tlv(name, default):  # noqa: N805 - tiny property factory
        def get(self):
            return getattr(self._tl, name, default)

        def put(self, v):
            setattr(self._tl, name, v)
        return property(get, put)

    _usage = _tlv("usage", None)
    _attempts = _tlv("attempts", 0)
    _util = _tlv("util", 0.0)

    # -- hooks ------------------------------------------------------------------------------------------------
    def build_user_prompt(self, inp: AgentInput) -> str:
        return inp.model_dump_json(exclude={"workflow_id"}, exclude_none=True)

    def expected_output_tokens(self, inp: AgentInput) -> int:
        return 1500

    def validate_output(self, inp: AgentInput, out: BaseModel) -> None:
        """Semantic checks; raise ValueError to trigger a bounded corrective retry."""

    def prepare(self, inp: AgentInput) -> AgentInput:
        """Tool-assisted enrichment (permissioned). Default: none."""
        return inp

    def execute(self, inp: AgentInput) -> BaseModel:
        """Default execution path = LLM. Deterministic agents override."""
        return self._llm_execute(inp)

    # -- public -----------------------------------------------------------------------------------------------
    def run(self, raw: AgentInput | dict) -> AgentResult:
        res = AgentResult(agent_id=self.agent_id, ok=False, prompt_version=self.prompt_version,
                          model_id=self.config.model_id)
        try:
            inp = raw if isinstance(raw, self.input_model) else self.input_model.model_validate(
                raw.model_dump() if isinstance(raw, BaseModel) else raw)
        except ValidationError as exc:
            res.error = AgentError(kind=ErrorKind.VALIDATION, message=f"invalid input: {exc.errors()[:3]}",
                                   agent_id=self.agent_id)
            return res
        meta = {"agent_id": self.agent_id, "prompt_version": self.prompt_version, "model_id": self.config.model_id,
                "story_id": inp.story_id, "story_version": inp.version, "workflow_id": inp.workflow_id}
        with trace_span(f"agent:{self.agent_id}", meta, self.tracing, "chain") as span:
            self.tools.calls = 0
            self._usage = Usage()
            self._attempts = 0
            self._util = 0.0
            computed = {"v": False}
            try:
                inp = self.prepare(inp)

                def compute():
                    computed["v"] = True
                    return self.execute(inp).model_dump(mode="json")

                def valid(v):
                    try:
                        self.output_model.model_validate(v)
                        return True
                    except Exception:
                        return False

                if self.cache is not None and self.config.use_cache and self.cache_namespace:
                    key = self.cache.build_key(agent=self.agent_id, prompt=self.prompt_version,
                                               prompt_hash=self._prompt_hash(), model=self.config.model_id,
                                               input=inp.model_dump(mode="json", exclude={"workflow_id"}))
                    data = self.cache.get_or_compute(self.cache_namespace, key, compute, validate=valid,
                                                     story_id=inp.story_id, version=inp.version)
                else:
                    data = compute()
                res.output = self.output_model.model_validate(data)
                res.ok = True
                res.cache_hit = not computed["v"]
            except AgentFailure as f:
                res.error = f.error
            except ContextOverflowError as exc:
                res.error = AgentError(kind=ErrorKind.CONTEXT_OVERFLOW, message=str(exc), agent_id=self.agent_id)
            except ToolPermissionError as exc:
                res.error = AgentError(kind=ErrorKind.TOOL, message=str(exc), agent_id=self.agent_id)
            except Exception as exc:  # never let an unexpected error look like success
                log.exception("agent %s crashed", self.agent_id)
                res.error = AgentError(kind=ErrorKind.WORKFLOW, message=f"{type(exc).__name__}: {exc}",
                                       agent_id=self.agent_id)
            res.usage, res.attempts, res.context_utilisation = self._usage, self._attempts, self._util
            res.usage.retries = max(0, self._attempts - 1)
            if res.error:
                res.error.attempts = self._attempts
            span.set(cache_status="hit" if res.cache_hit else "miss", ok=res.ok,
                     input_tokens=res.usage.input_tokens, output_tokens=res.usage.output_tokens,
                     context_utilisation=res.context_utilisation, attempts=res.attempts,
                     error_kind=res.error.kind.value if res.error else "")
        return res

    # -- LLM path ---------------------------------------------------------------------------------------------
    def _prompt_hash(self) -> str:
        if not self.uses_llm:
            return ""
        return self.prompts.load(self.agent_id, self.prompt_version)[1]

    def _fail(self, kind: ErrorKind, msg: str, retryable: bool = False) -> AgentFailure:
        return AgentFailure(AgentError(kind=kind, message=msg, agent_id=self.agent_id, retryable=retryable,
                                       attempts=self._attempts))

    def _llm_execute(self, inp: AgentInput) -> BaseModel:
        if self.llm is None or self.budget is None:
            raise self._fail(ErrorKind.WORKFLOW, "agent has no LLM client / budget service configured")
        system, _ = self.prompts.load(self.agent_id, self.prompt_version)
        user = self.build_user_prompt(inp)
        model = self.config.model_id
        expected = self.expected_output_tokens(inp)
        # Context budget is checked before EVERY call (overflow is non-retryable and never truncates silently).
        plan = self.budget.ensure_fits(self.agent_id, model, self.budget.estimate_tokens(system, model), 0,
                                       self.budget.estimate_tokens(user, model), expected)
        self._util = plan.utilisation
        spec_max = self.budget.registry.get(model).max_output
        last_err = ""
        extra = ""
        for attempt in range(1 + self.config.max_retries):
            self._attempts += 1
            req = LLMRequest(agent_id=self.agent_id, model=model, system=system, user=user + extra,
                             max_output_tokens=min(expected, spec_max), timeout=self.config.timeout_s,
                             metadata={"prompt_version": self.prompt_version, "story_id": inp.story_id})
            t0 = time.perf_counter()
            try:
                resp = self._call_with_timeout(req)
            except LLMRateLimitError as exc:
                last_err, kind = str(exc), ErrorKind.RATE_LIMIT
            except LLMTimeoutError as exc:
                last_err, kind = str(exc) or "timeout", ErrorKind.TIMEOUT
            except FutureTimeout:
                last_err, kind = f"no response within {self.config.timeout_s}s", ErrorKind.TIMEOUT
            except LLMModelError as exc:
                last_err, kind = str(exc), ErrorKind.MODEL
            else:
                self._usage.add(Usage(resp.input_tokens, resp.output_tokens, 1,
                                      (time.perf_counter() - t0) * 1000))
                try:
                    out = self.output_model.model_validate(extract_json(resp.text))
                    self.validate_output(inp, out)
                    return out
                except (ValidationError, ValueError) as exc:  # includes JSONDecodeError
                    last_err, kind = f"output invalid: {str(exc)[:300]}", ErrorKind.VALIDATION
                    extra = f"\n\nYour previous reply was rejected ({last_err}). Reply with corrected JSON only."
            if attempt < self.config.max_retries:
                self._sleep(self.config.backoff_base_s * (2 ** attempt))
        raise self._fail(kind, last_err or "failed", retryable=kind in (ErrorKind.RATE_LIMIT, ErrorKind.TIMEOUT,
                                                                       ErrorKind.MODEL))

    def _call_with_timeout(self, req: LLMRequest):
        ex = ThreadPoolExecutor(max_workers=1)
        try:
            return ex.submit(self.llm.invoke, req).result(timeout=self.config.timeout_s)
        finally:
            ex.shutdown(wait=False)
