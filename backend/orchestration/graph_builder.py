"""LangGraph assembly for the four workflows (spec section 5). Sub-chains are shared so behaviour is identical
whether a review runs inside story generation or on its own."""
from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from backend.orchestration import routers as R
from backend.orchestration.context import WorkflowContext
from backend.orchestration.graph_state import TERMINAL, WorkflowState
from backend.orchestration.nodes import make_node
from backend.orchestration.workflow_config import AGENT_FOR_STAGE


def _add(g: StateGraph, ctx: WorkflowContext, *names: str) -> None:
    for n in names:
        g.add_node(n, make_node(n, AGENT_FOR_STAGE.get(n), ctx))


def _seq(g: StateGraph, a: str, b: str) -> None:
    g.add_conditional_edges(a, lambda s, _b=b: END if s.get("status") in TERMINAL else _b, {b: b, END: END})


def _review_chain(g: StateGraph, ctx: WorkflowContext, final: str, entry_from: str | None) -> None:
    """humanise -> continuity -> editorial -> safety with routers, bounded revision and human interrupts."""
    m = ctx.config.max_revision_attempts
    _add(g, ctx, "humanise", "continuity", "editorial", "safety", "revise", "human_review", "terminate")
    stage_targets = ["humanise", "continuity", "editorial", "safety", final]
    if entry_from:
        g.add_conditional_edges(
            entry_from, lambda s: END if s.get("status") in TERMINAL else (
                "humanise" if "humanise" in (s.get("stages_enabled") or []) else R.next_review(s, "humanise", final)),
            {t: t for t in stage_targets} | {END: END})
    g.add_conditional_edges("humanise", R.after_humanise(final, m), {t: t for t in stage_targets} | {END: END})
    g.add_conditional_edges("continuity", R.after_continuity(final, m),
                            {t: t for t in ["editorial", "safety", final, "revise", "human_review"]} | {END: END})
    g.add_conditional_edges("editorial", R.after_editorial(final, m),
                            {t: t for t in ["safety", final, "revise", "human_review", "terminate"]} | {END: END})
    g.add_conditional_edges("safety", R.after_safety(final, m),
                            {t: t for t in [final, "revise", "human_review", "terminate"]} | {END: END})
    g.add_conditional_edges("revise", R.after_revise(final),
                            {t: t for t in ["continuity", "editorial", "safety", final]} | {END: END})
    g.add_conditional_edges("human_review", R.after_human_review(final),
                            {t: t for t in ["revise", "continuity", "editorial", "safety", final, "terminate"]}
                            | {END: END})
    g.add_edge("terminate", END)


def _finish(g: StateGraph, ctx: WorkflowContext) -> None:
    _add(g, ctx, "finish")
    g.add_edge("finish", END)


def build_story_generation_graph(ctx: WorkflowContext, checkpointer):
    g = StateGraph(WorkflowState)
    _add(g, ctx, "validate", "planner", "writer", "images", "distribution", "readiness", "approval", "queue")
    g.add_edge(START, "validate")
    _seq(g, "validate", "planner")
    _seq(g, "planner", "writer")
    _review_chain(g, ctx, final="images", entry_from="writer")
    for a, b in (("images", "distribution"), ("distribution", "readiness"), ("readiness", "approval"),
                 ("approval", "queue"), ("queue", "finish")):
        _seq(g, a, b)
    _finish(g, ctx)
    return g.compile(checkpointer=checkpointer)


def build_story_review_graph(ctx: WorkflowContext, checkpointer):
    g = StateGraph(WorkflowState)
    _add(g, ctx, "validate")
    g.add_edge(START, "validate")
    _review_chain(g, ctx, final="finish", entry_from="validate")
    _finish(g, ctx)
    return g.compile(checkpointer=checkpointer)


def build_distribution_graph(ctx: WorkflowContext, checkpointer):
    g = StateGraph(WorkflowState)
    _add(g, ctx, "validate", "images", "distribution", "readiness")
    g.add_edge(START, "validate")
    for a, b in (("validate", "images"), ("images", "distribution"), ("distribution", "readiness"),
                 ("readiness", "finish")):
        _seq(g, a, b)
    _finish(g, ctx)
    return g.compile(checkpointer=checkpointer)


def build_publishing_graph(ctx: WorkflowContext, checkpointer):
    """Publishing-readiness: validate -> readiness -> human approval (interrupt) -> queue hand-off."""
    g = StateGraph(WorkflowState)
    _add(g, ctx, "validate", "readiness", "approval", "queue")
    g.add_edge(START, "validate")
    for a, b in (("validate", "readiness"), ("readiness", "approval"), ("approval", "queue"), ("queue", "finish")):
        _seq(g, a, b)
    _finish(g, ctx)
    return g.compile(checkpointer=checkpointer)
