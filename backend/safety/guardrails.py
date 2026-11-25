"""Pre-publish content gate. FAILS CLOSED: any violation, or any error inside the gate, blocks the publish.

Validators are plain functions (testable without any library). When ``guardrails-ai`` is installed AND its remote
telemetry is disabled, the same validators are executed through a Guardrails ``Guard``; otherwise the native runner
is used. Guardrails AI ships telemetry on by default and would send draft text off-machine, so we never use it
unless ``guardrails configure --disable-metrics`` has been run."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Callable

from backend.safety.pii import PiiService, PiiUnavailable

log = logging.getLogger("midnight.safety.guard")

Validator = Callable[[str], "list[Violation]"]


@dataclass(frozen=True)
class Violation:
    rule: str
    message: str
    severity: str = "high"


@dataclass
class GuardReport:
    passed: bool
    violations: list[Violation] = field(default_factory=list)
    engine: str = "native"

    def summary(self) -> str:
        return "; ".join(f"{v.rule}: {v.message}" for v in self.violations)


_INJECTION = re.compile(
    r"ignore (all |any )?(previous|prior|above) (instructions|prompts)|disregard (the |your )?(system|previous)"
    r"|you are now (in )?(dan|developer mode)|reveal (your )?(system )?prompt|as an ai (language )?model",
    re.I)
_PLACEHOLDER = re.compile(r"\{\{[^}]*\}\}|\[(?:INSERT|TODO|TBD|PLACEHOLDER)[^\]]*\]|lorem ipsum", re.I)
_LLM_ARTIFACT = re.compile(r"^\s*(sure[,!]|certainly[,!]|here(?:'s| is) (?:the|your) (?:story|revised))", re.I)
_JSON_LEAK = re.compile(r'^\s*[\[{]\s*"(?:text|title|status)"\s*:', re.I)


def make_validators(min_chars: int = 20, max_chars: int = 200_000, pii: PiiService | None = None) -> list[Validator]:
    def length(text: str):
        n = len(text.strip())
        if n < min_chars:
            return [Violation("length", f"content too short ({n} chars)")]
        if n > max_chars:
            return [Violation("length", f"content too long ({n} chars)")]
        return []

    def injection(text: str):
        m = _INJECTION.search(text)
        return [Violation("prompt_injection", f"injection/leak marker in output: {m.group(0)!r}")] if m else []

    def placeholders(text: str):
        m = _PLACEHOLDER.search(text)
        return [Violation("placeholder", f"unfilled placeholder: {m.group(0)!r}")] if m else []

    def artifacts(text: str):
        if _LLM_ARTIFACT.search(text) or _JSON_LEAK.search(text):
            return [Violation("llm_artifact", "model chatter or raw JSON leaked into the content", "medium")]
        return []

    vs: list[Validator] = [length, injection, placeholders, artifacts]
    if pii is not None:
        def pii_rule(text: str):
            hits = pii.scan(text)  # PiiUnavailable propagates -> gate fails closed
            kinds = sorted({h.entity for h in hits})
            return [Violation("pii", f"{len(hits)} PII item(s): {', '.join(kinds)}", "critical")] if hits else []
        vs.append(pii_rule)
    return vs


def _library_usable() -> bool:
    try:
        from guardrails.classes.rc import RC
        return RC.load().enable_metrics is False
    except Exception:
        return False


class ContentGuard:
    def __init__(self, validators: list[Validator] | None = None, pii: PiiService | None = None,
                 use_library: bool = True):
        self.validators = validators if validators is not None else make_validators(pii=pii)
        self._lib = use_library and _library_usable()
        if use_library and not self._lib:
            log.info("guardrails-ai not used (not installed or telemetry not disabled); native gate active")

    def check(self, text: str) -> GuardReport:
        try:
            if self._lib:
                return self._check_library(text)
            return self._check_native(text)
        except PiiUnavailable as exc:
            return GuardReport(False, [Violation("pii_engine", str(exc), "critical")])
        except Exception as exc:  # fail closed
            log.exception("guardrail gate error")
            return GuardReport(False, [Violation("gate_error", f"{type(exc).__name__}: {exc}", "critical")])

    def _check_native(self, text: str) -> GuardReport:
        vs: list[Violation] = []
        for v in self.validators:
            vs.extend(v(text))
        return GuardReport(not vs, vs)

    def _check_library(self, text: str) -> GuardReport:
        from guardrails import Guard, OnFailAction
        from guardrails.validators import FailResult, PassResult, Validator as GValidator, register_validator

        found: list[Violation] = []
        guard = Guard()
        for i, fn in enumerate(self.validators):
            def validate(self_, value, metadata, _fn=fn):
                vio = _fn(value)
                found.extend(vio)
                return FailResult(error_message="; ".join(v.message for v in vio)) if vio else PassResult()
            cls = type(f"MidnightRule{i}", (GValidator,), {"validate": validate})
            register_validator(name=f"midnight/rule_{i}_{id(self)}", data_type="string")(cls)
            guard = guard.use(cls(on_fail=OnFailAction.NOOP))
        guard.validate(text)
        return GuardReport(not found, found, engine="guardrails-ai")
