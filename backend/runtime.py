"""Application runtime wiring: ONE CacheService / ContextBudgetService / PublishingQueueService shared by the
API, the agents, the WorkflowService and the scheduler.

``build_runtime`` is called once from the FastAPI lifespan (see ``backend.main``) and its pieces are exposed on
``app.state``. ``AppWorkflowService`` builds its WorkflowContext from those shared pieces instead of creating
private copies, so /cache/stats, /context/stats and the dashboard reflect real agent usage.
"""
from __future__ import annotations

import importlib
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Optional

from backend.config import Settings
from backend.orchestration.workflow_service import WorkflowService, reset_workflow_service
from backend.services.cache_service import CacheService
from backend.services.content_path_manager import ContentPathManager
from backend.services.context_budget_service import ContextBudgetService
from backend.services.llm_client import build_model_registry

log = logging.getLogger("midnight.runtime")

# The agents name platforms after content formats; the publishing queue names them after destinations.
QUEUE_PLATFORM = {"youtube_shorts": "youtube", "instagram_reels": "instagram"}


class ImageToolError(RuntimeError):
    pass


def load_image_tool(spec: str) -> Optional[Callable[[dict, str, int], str]]:
    """Resolve ``IMAGE_GENERATOR=package.module:callable``.

    The callable receives ``(asset_spec: dict, story_id: str, version: int)`` and must return a stored asset
    reference (str). No real image backend is bundled; when unset the ImageAgent only produces prompts and
    the workflow's readiness gate reports "no validated image assets" until assets are attached.
    """
    spec = (spec or "").strip()
    if not spec:
        return None
    mod_name, _, attr = spec.partition(":")
    if not mod_name or not attr:
        raise ImageToolError(f"IMAGE_GENERATOR must look like 'package.module:callable', got {spec!r}")
    try:
        fn = getattr(importlib.import_module(mod_name), attr)
    except (ImportError, AttributeError) as exc:
        raise ImageToolError(f"IMAGE_GENERATOR {spec!r} could not be imported: {exc}") from exc
    if not callable(fn):
        raise ImageToolError(f"IMAGE_GENERATOR {spec!r} is not callable")
    return fn


class QueuePortAdapter:
    """Adapts PublishingQueueService.enqueue(story_id, version, platform, scheduled_at) to the workflow's
    ``enqueue(job: dict)`` port. Approval/eligibility is enforced by the queue service itself."""

    def __init__(self, service: Any):
        self.service = service

    def enqueue(self, job: dict) -> Any:
        when = job.get("scheduled_for")
        if isinstance(when, str) and when:
            from backend.api.common import naive_utc
            when = naive_utc(datetime.fromisoformat(when.replace("Z", "+00:00")))
        elif not isinstance(when, datetime):
            when = None
        platform = QUEUE_PLATFORM.get(job["platform"], job["platform"])
        return self.service.enqueue(job["story_id"], int(job["version"]), platform, when)["id"]


class AppWorkflowService(WorkflowService):
    """WorkflowService whose lazily-built context reuses the application's shared services."""

    def __init__(self, settings: Settings, cache: CacheService, budget: ContextBudgetService,
                 queue_port: Any = None, image_tool: Optional[Callable] = None, llm: Any = None, **kw):
        super().__init__(**kw)
        self._settings, self._cache, self._budget = settings, cache, budget
        self._queue_port, self._image_tool, self._llm = queue_port, image_tool, llm

    @property
    def ctx(self):
        if self._ctx is None:
            from backend.agents import AgentConfig
            from backend.orchestration.context import build_context
            extra = {"image": {"generate_image": self._image_tool}} if self._image_tool else None
            self._ctx = build_context(llm=self._llm, settings=self._settings,
                                      # the publishing agent makes one queue_job call per platform (+ checks)
                                      agent_config=AgentConfig(model_id=self._settings.openai_model or "gpt-4o",
                                                               max_tool_calls=20), cache=self._cache, budget=self._budget,
                                      path_manager=ContentPathManager(self._settings.data_path / "content"),
                                      queue_port=self._queue_port, extra_tools=extra)
        return self._ctx


@dataclass
class Runtime:
    cache: CacheService
    budget: ContextBudgetService
    queue: Any
    workflow: AppWorkflowService


def build_runtime(settings: Settings, queue: Any = None, llm: Any = None) -> Runtime:
    from backend.automation.publishing_queue import PublishingQueueService
    cache = CacheService(settings)
    budget = ContextBudgetService(build_model_registry(settings), settings)
    queue = queue or PublishingQueueService(max_retries=settings.publishing_max_retries,
                                            data_dir=settings.data_path)
    try:
        image_tool = load_image_tool(getattr(settings, "image_generator", ""))
    except ImageToolError as exc:
        log.error("image tool disabled: %s", exc, extra={"operation": "startup"})
        image_tool = None
    wf = AppWorkflowService(settings, cache, budget, QueuePortAdapter(queue), image_tool, llm,
                            checkpoint_path=str(settings.data_path / "checkpoints.db"))
    return Runtime(cache, budget, queue, wf)


def install_runtime(rt: Runtime) -> None:
    reset_workflow_service(rt.workflow)


def uninstall_runtime() -> None:
    reset_workflow_service(None)
