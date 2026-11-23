"""ContextBudgetService: mandatory pre-flight check before every LLM call.

available_input = context_limit - system - agent - conversation - expected_output
                  - tool_reserve - safety_margin
``fits`` is False when available_input < 0 or expected_output exceeds the model's max output.

Token estimation: tiktoken is used only for providers/models it genuinely supports (OpenAI
families); otherwise a deliberately conservative estimator (never under-counts typical English
prose): max(ceil(chars/3), ceil(words*1.5)). Limitation: for non-OpenAI tokenizers, code, or
non-Latin scripts the real count can still differ; the safety margin absorbs ordinary error.
"""
from __future__ import annotations

import math
import re
import threading
from collections import defaultdict
from dataclasses import dataclass

from backend.config import Settings
from backend.services.model_registry import ModelRegistry

_WORD = re.compile(r"\S+")


class ContextOverflowError(Exception):
    def __init__(self, message: str, plan: "BudgetPlan | None" = None):
        super().__init__(message)
        self.plan = plan


@dataclass(frozen=True)
class BudgetPlan:
    available_input: int
    reserved_output: int
    safety_margin: int
    fits: bool
    context_limit: int = 0
    tool_reserve: int = 0
    used: int = 0
    utilisation: float = 0.0
    reason: str = ""


def conservative_estimate(text: str) -> int:
    if not text:
        return 0
    return max(math.ceil(len(text) / 3), math.ceil(len(_WORD.findall(text)) * 1.5))


class ContextBudgetService:
    def __init__(self, registry: ModelRegistry | None = None, settings: Settings | None = None,
                 safety_margin_ratio: float = 0.05, min_safety_margin: int = 256):
        self.registry = registry or ModelRegistry(settings)
        self.safety_margin_ratio = safety_margin_ratio
        self.min_safety_margin = min_safety_margin
        self._lock = threading.Lock()
        self._stats: dict[str, dict] = defaultdict(lambda: {"calls": 0, "overflows": 0, "max_utilisation": 0.0,
                                                           "total_utilisation": 0.0})
        self._encoders: dict[str, object] = {}

    # -- estimation ----------------------------------------------------
    def _encoder(self, model_id: str):
        spec = self.registry.get(model_id)
        if spec.provider.lower() != "openai":
            return None
        if model_id not in self._encoders:
            enc = None
            try:
                import tiktoken

                try:
                    enc = tiktoken.encoding_for_model(model_id)
                except KeyError:
                    enc = tiktoken.get_encoding("cl100k_base")
            except Exception:
                enc = None  # offline / not installed: use the conservative estimator
            self._encoders[model_id] = enc
        return self._encoders[model_id]

    def estimate_tokens(self, text: str, model_id: str = "") -> int:
        if not text:
            return 0
        enc = self._encoder(model_id) if model_id else None
        conservative = conservative_estimate(text)
        if enc is not None:
            try:
                # Exact count, plus a small allowance for message framing.
                return len(enc.encode(text, disallowed_special=())) + 4
            except Exception:
                pass
        return conservative

    # -- planning ------------------------------------------------------
    def plan(self, agent_id: str, model_id: str, system_tokens: int, agent_tokens: int, convo_tokens: int,
             expected_output: int, tool_reserve: int = 0) -> BudgetPlan:
        spec = self.registry.get(model_id)
        limit = spec.context_limit
        margin = max(self.min_safety_margin, math.ceil(limit * self.safety_margin_ratio))
        prompt = system_tokens + agent_tokens + convo_tokens
        available = limit - prompt - expected_output - tool_reserve - margin
        reason = ""
        fits = available >= 0
        if not fits:
            reason = f"prompt+output+reserves exceed context limit {limit} by {-available}"
        if expected_output > spec.max_output:
            fits = False
            reason = f"expected output {expected_output} exceeds model max output {spec.max_output}"
        used = prompt + expected_output + tool_reserve
        util = used / limit if limit else 0.0
        with self._lock:
            st = self._stats[agent_id]
            st["calls"] += 1
            st["total_utilisation"] += util
            st["max_utilisation"] = max(st["max_utilisation"], util)
            if not fits:
                st["overflows"] += 1
        return BudgetPlan(available_input=available, reserved_output=expected_output, safety_margin=margin,
                          fits=fits, context_limit=limit, tool_reserve=tool_reserve, used=used,
                          utilisation=round(util, 4), reason=reason)

    def ensure_fits(self, agent_id: str, model_id: str, system_tokens: int, agent_tokens: int,
                    convo_tokens: int, expected_output: int, tool_reserve: int = 0) -> BudgetPlan:
        p = self.plan(agent_id, model_id, system_tokens, agent_tokens, convo_tokens, expected_output, tool_reserve)
        if not p.fits:
            raise ContextOverflowError(f"{agent_id}/{model_id}: {p.reason}", p)
        return p

    def stats(self) -> dict:
        with self._lock:
            out = {}
            for agent, st in self._stats.items():
                calls = st["calls"]
                out[agent] = {"calls": calls, "overflows": st["overflows"],
                              "max_utilisation": round(st["max_utilisation"], 4),
                              "avg_utilisation": round(st["total_utilisation"] / calls, 4) if calls else 0.0}
            return {"agents": out, "total_calls": sum(v["calls"] for v in out.values()),
                    "total_overflows": sum(v["overflows"] for v in out.values())}
