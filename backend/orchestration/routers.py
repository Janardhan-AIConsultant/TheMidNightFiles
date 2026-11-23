"""Conditional routers. Pure functions of state: no I/O, no side effects. Revision loops are bounded by
``max_attempts`` and always fall through to human review, never to another automatic attempt."""
from __future__ import annotations

from typing import Callable

from langgraph.graph import END

from backend.orchestration.graph_state import TERMINAL
from backend.orchestration.workflow_config import REVIEW_STAGES

AFTER_REVIEWS_GENERATION = "images"
AFTER_REVIEWS_REVIEW = "finish"


def next_review(state: dict, after: str | None, final: str, pool=REVIEW_STAGES) -> str:
    enabled = state.get("stages_enabled") or list(REVIEW_STAGES)
    seq = list(pool)
    start = seq.index(after) + 1 if after in seq else 0
    for st in seq[start:]:
        if st in enabled:
            return st
    return final


def first_review_stage(final: str) -> Callable[[dict], str]:
    def route(state: dict) -> str:
        if state.get("status") in TERMINAL:
            return END
        return next_review(state, None, final)
    return route


def _guard(fn: Callable[[dict], str]) -> Callable[[dict], str]:
    def route(state: dict) -> str:
        return END if state.get("status") in TERMINAL else fn(state)
    return route


def revise_or_human(state: dict, max_attempts: int) -> str:
    return "revise" if state.get("revision_attempts", 0) < max_attempts else "human_review"


def after_humanise(final: str, max_attempts: int):
    return _guard(lambda s: next_review(s, "humanise", final))


def after_continuity(final: str, max_attempts: int):
    def route(s: dict) -> str:
        st = s.get("continuity_status")
        if st == "ISSUES_FOUND" and any(f.get("severity") in ("high", "critical")
                                        for f in s.get("pending_findings", [])):
            return revise_or_human(s, max_attempts)
        if st in ("HUMAN_REVIEW_REQUIRED", "NOT_REVIEWED", None) and "continuity" in (s.get("stages_enabled") or []):
            return "human_review"  # unknown/uncertain outcome is never treated as a pass
        return next_review(s, "continuity", final)
    return _guard(route)


def after_editorial(final: str, max_attempts: int):
    def route(s: dict) -> str:
        st = s.get("editorial_status")
        if st == "APPROVED":
            return next_review(s, "editorial", final)
        if st == "NEEDS_REVISION":
            return revise_or_human(s, max_attempts)
        if st == "REJECTED":
            return "terminate"
        return "human_review"  # HUMAN_REVIEW_REQUIRED or anything unexpected
    return _guard(route)


def after_safety(final: str, max_attempts: int):
    def route(s: dict) -> str:
        st = s.get("safety_status")
        if st == "PASSED" and s.get("safety_coverage", 0) == 1.0:
            return next_review(s, "safety", final)
        if st == "NEEDS_REVISION":
            return revise_or_human(s, max_attempts)
        if st == "BLOCKED":
            return "terminate"
        return "human_review"
    return _guard(route)


def after_revise(final: str):
    """A revision creates a new version: restart the review chain (never re-humanise automatically)."""
    return _guard(lambda s: next_review(s, "humanise", final))


def after_human_review(final: str):
    def route(s: dict) -> str:
        a = s.get("human_action")
        if a == "rerun":
            return next_review(s, "humanise", final)
        return {"revise": "revise", "reject": "terminate"}.get(a, "terminate")
    return _guard(route)
