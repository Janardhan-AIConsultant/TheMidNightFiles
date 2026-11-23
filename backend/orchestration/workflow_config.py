"""Workflow-level configuration and static definitions."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from backend.config import Settings, get_settings

REVIEW_STAGES = ["humanise", "continuity", "editorial", "safety"]

STAGES = {
    "story_generation": ["validate", "planner", "writer", "humanise", "continuity", "editorial", "safety", "images",
                         "distribution", "readiness", "approval", "queue"],
    "story_review": ["validate"] + REVIEW_STAGES,
    "distribution": ["validate", "images", "distribution", "readiness"],
    "publishing": ["validate", "readiness", "approval", "queue"],
}

AGENT_FOR_STAGE = {"planner": "planner", "writer": "writer", "humanise": "humanisation", "continuity": "continuity",
                   "editorial": "editorial", "safety": "safety", "images": "image", "distribution": "distribution",
                   "readiness": "publishing", "queue": "publishing", "revise": "writer"}


@dataclass
class WorkflowConfig:
    max_revision_attempts: int = 3
    checkpoint_path: str = "./data/checkpoints.db"

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> "WorkflowConfig":
        s = settings or get_settings()
        return cls(max_revision_attempts=s.max_revision_attempts,
                   checkpoint_path=str(Path(s.data_path) / "checkpoints.db"))
