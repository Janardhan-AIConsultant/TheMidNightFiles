"""Typed, serialisable workflow state. Holds references and hashes - never story text."""
from __future__ import annotations

from typing import Any, TypedDict

TERMINAL = {"completed", "failed", "terminated", "stale"}


class WorkflowState(TypedDict, total=False):
    workflow_id: str
    thread_id: str
    workflow_type: str
    request: dict
    story_id: str
    version: int
    content_hash: str
    profile: dict
    brief: dict
    synopsis: str
    series_id: int | None
    stages_enabled: list[str]
    stages: dict[str, str]
    current_agent: str
    status: str                      # running | awaiting_human | completed | failed | terminated | stale
    continuity_status: str
    editorial_status: str
    safety_status: str
    safety_coverage: float
    pending_findings: list[dict]
    revision_target: str             # writer | humanise
    revision_attempts: int
    human_action: str
    human_reason: str
    images: list[dict]
    distribution_ref: dict[str, str]
    approval_status: str
    approval_version: int | None
    publishing_status: str
    retries: int
    errors: list[dict]
    context_budget: dict[str, Any]
    token_usage: dict[str, Any]


def empty_usage() -> dict:
    return {"input_tokens": 0, "output_tokens": 0, "calls": 0, "by_agent": {}}
