"""The ten Midnight Files agents."""
from __future__ import annotations

from typing import Callable

from backend.agents.base import (AgentConfig, AgentError, AgentFailure, AgentResult, BaseAgent, ErrorKind,
                                 PromptStore, ToolPermissionError, Usage)
from backend.agents.content import HumanisationAgent, PlannerAgent, WriterAgent
from backend.agents.media import DistributionAgent, ImageAgent
from backend.agents.ops import AnalyticsAgent, PublishingAgent
from backend.agents.reviewers import ContinuityAgent, EditorialAgent, SafetyAgent

AGENT_CLASSES = [PlannerAgent, WriterAgent, HumanisationAgent, ContinuityAgent, EditorialAgent, SafetyAgent,
                 ImageAgent, DistributionAgent, PublishingAgent, AnalyticsAgent]


def build_agents(llm, budget, cache=None, config: AgentConfig | None = None,
                 tools: dict[str, dict[str, Callable]] | None = None, tracing: bool | None = None
                 ) -> dict[str, BaseAgent]:
    """``tools[agent_id]`` supplies that agent's (allow-listed) tool callables."""
    tools = tools or {}
    return {c.agent_id: c(llm=llm, budget=budget, cache=cache, config=config, tools=tools.get(c.agent_id),
                          tracing=tracing) for c in AGENT_CLASSES}


__all__ = ["AGENT_CLASSES", "build_agents", "AgentConfig", "AgentError", "AgentFailure", "AgentResult", "BaseAgent",
           "ErrorKind", "PromptStore", "ToolPermissionError", "Usage", "PlannerAgent", "WriterAgent",
           "HumanisationAgent", "ContinuityAgent", "EditorialAgent", "SafetyAgent", "ImageAgent",
           "DistributionAgent", "PublishingAgent", "AnalyticsAgent"]
