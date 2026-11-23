"""Dependency container shared by graph nodes + in-process event bus."""
from __future__ import annotations

import threading
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Optional, Protocol

from backend.agents import AgentConfig, BaseAgent, build_agents
from backend.config import Settings, get_settings
from backend.orchestration.workflow_config import WorkflowConfig
from backend.services.approval_service import ApprovalService
from backend.services.cache_invalidation_service import CacheInvalidationService
from backend.services.cache_service import CacheService
from backend.services.context_budget_service import ContextBudgetService
from backend.services.llm_client import LLMClient, build_model_registry
from backend.services.story_service import StoryService


class PublishingQueuePort(Protocol):
    """Implemented by the publishing owner; the workflow only hands over validated jobs."""

    def enqueue(self, job: dict) -> Any: ...


class EventBus:
    """Per-workflow ordered events kept in memory for SSE (bounded). Not a log store."""

    def __init__(self, cap: int = 2000):
        self._ev: dict[str, list[dict]] = defaultdict(list)
        self._lock = threading.Lock()
        self.cap = cap

    def publish(self, wid: str, event: dict) -> None:
        with self._lock:
            lst = self._ev[wid]
            event = {"seq": (lst[-1]["seq"] + 1) if lst else 1, "workflow_id": wid,
                     "ts": datetime.now(timezone.utc).isoformat(), **event}
            lst.append(event)
            del lst[:-self.cap]

    def since(self, wid: str, seq: int) -> list[dict]:
        with self._lock:
            return [e for e in self._ev.get(wid, []) if e["seq"] > seq]

    def known(self, wid: str) -> bool:
        with self._lock:
            return bool(self._ev.get(wid))


@dataclass
class WorkflowContext:
    agents: dict[str, BaseAgent]
    budget: ContextBudgetService
    cache: Optional[CacheService]
    settings: Settings
    session_factory: Callable[[], Any]
    config: WorkflowConfig
    path_manager: Any = None
    queue_port: Optional[PublishingQueuePort] = None
    events: EventBus = field(default_factory=EventBus)
    agent_stats: dict[str, dict] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def story_service(self, session) -> StoryService:
        cb = CacheInvalidationService(self.cache).on_new_version if self.cache is not None else None
        return StoryService(session, self.path_manager, on_new_version=cb)

    def touch_agent(self, agent_id: str, **upd) -> None:
        with self._lock:
            st = self.agent_stats.setdefault(agent_id, {"runs": 0, "failures": 0, "active": 0, "last_run": None,
                                                        "input_tokens": 0, "output_tokens": 0})
            for k, v in upd.items():
                if k in ("runs", "failures", "active", "input_tokens", "output_tokens"):
                    st[k] += v
                else:
                    st[k] = v


def build_context(llm: LLMClient | None = None, settings: Settings | None = None,
                  session_factory: Callable[[], Any] | None = None, cache: CacheService | None = None,
                  budget: ContextBudgetService | None = None, agent_config: AgentConfig | None = None,
                  config: WorkflowConfig | None = None, path_manager: Any = None, queue_port=None,
                  extra_tools: dict[str, dict[str, Callable]] | None = None, tracing: bool | None = None
                  ) -> WorkflowContext:
    from backend import database
    from backend.services.llm_client import build_llm_client
    settings = settings or get_settings()
    llm = llm or build_llm_client(settings)
    session_factory = session_factory or database.get_session
    if cache is None:
        cache = CacheService(settings)
    budget = budget or ContextBudgetService(build_model_registry(settings), settings)
    agent_config = agent_config or AgentConfig(model_id=settings.openai_model or "gpt-4o")

    def current_version(story_id: str) -> int:
        with session_factory() as s:
            return StoryService(s).get_story(story_id).current_version

    def is_publishable(story_id: str, version: int):
        with session_factory() as s:
            return ApprovalService(s).is_publishable(story_id, version)

    tools: dict[str, dict[str, Callable]] = {
        "publishing": {"current_version": current_version, "is_publishable": is_publishable}}
    if queue_port is not None:
        tools["publishing"]["queue_job"] = queue_port.enqueue
    for k, v in (extra_tools or {}).items():
        tools.setdefault(k, {}).update(v)
    agents = build_agents(llm, budget, cache, agent_config, tools, tracing)
    return WorkflowContext(agents=agents, budget=budget, cache=cache, settings=settings,
                           session_factory=session_factory, config=config or WorkflowConfig.from_settings(settings),
                           path_manager=path_manager, queue_port=queue_port)
