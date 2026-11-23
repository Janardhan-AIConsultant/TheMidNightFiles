"""Maps workflow types to graph builders."""
from __future__ import annotations

from backend.orchestration.graph_builder import (build_distribution_graph, build_publishing_graph,
                                                 build_story_generation_graph, build_story_review_graph)

BUILDERS = {
    "story_generation": build_story_generation_graph,
    "story_review": build_story_review_graph,
    "distribution": build_distribution_graph,
    "publishing": build_publishing_graph,
}

# POST /workflows aliases used by the API (story-level review endpoints)
ALIASES = {"generate": "story_generation", "review": "story_review", "readiness": "publishing"}


def resolve(workflow_type: str) -> str:
    t = ALIASES.get(workflow_type, workflow_type)
    if t not in BUILDERS:
        raise ValueError(f"unknown workflow_type {workflow_type!r}; supported: {sorted(BUILDERS)}")
    return t
