"""Facade used by the API layer. Owns graph compilation, checkpointing, background execution and SSE events."""
from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
import uuid
from typing import Any, AsyncIterator, Optional

from langgraph.types import Command

from backend.orchestration.checkpoint_manager import WorkflowRegistry, get_checkpointer
from backend.orchestration.context import WorkflowContext, build_context
from backend.orchestration.graph_state import TERMINAL, empty_usage
from backend.orchestration.nodes import latest_version
from backend.orchestration.workflow_config import STAGES
from backend.orchestration.workflow_registry import BUILDERS, resolve

log = logging.getLogger("midnight.agent.workflow")


class WorkflowError(Exception):
    pass


class WorkflowNotFound(WorkflowError):
    pass


class WorkflowStateError(WorkflowError):
    """Operation not valid in the workflow's current status (maps to HTTP 409)."""


class StaleVersionError(WorkflowStateError):
    """The story changed since the workflow was checkpointed; it must not resume toward publishing."""


class WorkflowService:
    def __init__(self, ctx: WorkflowContext | None = None, checkpoint_path: str | None = None, inline: bool = False):
        self._ctx = ctx
        self._path = checkpoint_path
        self.inline = inline
        self._graphs: dict[str, Any] = {}
        self._registry: WorkflowRegistry | None = None
        self._locks: dict[str, threading.Lock] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._guard = threading.Lock()

    # -- lazy wiring ---------------------------------------------------------------------------------------------
    @property
    def ctx(self) -> WorkflowContext:
        if self._ctx is None:
            self._ctx = build_context()
        return self._ctx

    @property
    def path(self) -> str:
        return self._path or self.ctx.config.checkpoint_path

    @property
    def registry(self) -> WorkflowRegistry:
        if self._registry is None:
            self._registry = WorkflowRegistry(self.path)
        return self._registry

    def _graph(self, wtype: str):
        with self._guard:
            if wtype not in self._graphs:
                self._graphs[wtype] = BUILDERS[wtype](self.ctx, get_checkpointer(self.path))
            return self._graphs[wtype]

    def _lock(self, wid: str) -> threading.Lock:
        with self._guard:
            return self._locks.setdefault(wid, threading.Lock())

    @staticmethod
    def _cfg(row: dict) -> dict:
        return {"configurable": {"thread_id": row["thread_id"]}, "recursion_limit": 100}

    # -- public API ----------------------------------------------------------------------------------------------
    def start(self, request: dict) -> str:
        request = dict(request or {})
        try:
            wtype = resolve(request.get("workflow_type", "story_generation"))
        except ValueError as exc:
            raise WorkflowError(str(exc)) from exc
        wid, tid = f"WF-{uuid.uuid4().hex[:12]}", f"thread-{uuid.uuid4().hex}"
        request["workflow_type"] = wtype
        self.registry.create(wid, tid, wtype, request)
        state = {"workflow_id": wid, "thread_id": tid, "workflow_type": wtype, "request": request,
                 "stages": {n: "pending" for n in STAGES[wtype]}, "status": "running", "retries": 0, "errors": [],
                 "revision_attempts": 0, "images": [], "token_usage": empty_usage(), "context_budget": {},
                 "approval_status": "NOT_REVIEWED", "publishing_status": "not_started"}
        if request.get("story_id"):
            state["story_id"] = request["story_id"]
        self.ctx.events.publish(wid, {"type": "workflow_started", "workflow_type": wtype})
        self._dispatch(wid, state)
        return wid

    def resume(self, workflow_id: str, decision: dict) -> None:
        row = self._row(workflow_id)
        if row["status"] != "awaiting_human":
            raise WorkflowStateError(f"workflow {workflow_id} is {row['status']}, not awaiting a human decision")
        graph = self._graph(row["workflow_type"])
        snap = graph.get_state(self._cfg(row))
        payload = next((i.value for t in snap.tasks for i in t.interrupts), {}) or {}
        if payload.get("type") == "human_approval":
            ver, h = latest_version(self.ctx, payload["story_id"])
            if ver != payload["version"] or h != payload["content_hash"]:
                self.ctx.events.publish(workflow_id, {"type": "workflow_status", "status": "stale",
                                                      "detail": f"story is now v{ver}; workflow holds "
                                                                f"v{payload['version']}"})
                self.registry.update(workflow_id, status="stale")
                raise StaleVersionError(f"story {payload['story_id']} is now v{ver}; workflow holds "
                                        f"v{payload['version']} and cannot resume toward publishing")
        self.registry.update(workflow_id, status="running")
        self.ctx.events.publish(workflow_id, {"type": "workflow_resumed", "decision": decision.get("decision")
                                              or decision.get("action")})
        self._dispatch(workflow_id, Command(resume=decision))

    def recover_interrupted(self) -> list[str]:
        """After an application restart: continue workflows that were mid-run from their last checkpoint."""
        rows, _ = self.registry.list(1000, 0)
        out = []
        for r in rows:
            if r["status"] in ("running", "interrupted") and r["workflow_id"] not in self._threads:
                self._dispatch(r["workflow_id"], None)
                out.append(r["workflow_id"])
        return out

    def get(self, workflow_id: str) -> dict:
        row = self._row(workflow_id)
        values: dict = {}
        awaiting: Optional[dict] = None
        waiting_node = None
        try:
            snap = self._graph(row["workflow_type"]).get_state(self._cfg(row))
            values = dict(snap.values or {})
            for t in snap.tasks:
                for i in t.interrupts:
                    awaiting, waiting_node = i.value, t.name
        except Exception as exc:
            log.warning("could not read checkpoint for %s: %s", workflow_id, exc)
        stages_state = dict(values.get("stages") or {})
        if waiting_node:
            stages_state[waiting_node] = "awaiting_human"
        order = list(STAGES[row["workflow_type"]])
        order += [k for k in stages_state if k not in order]
        usage = values.get("token_usage") or empty_usage()
        return {"workflow_id": row["workflow_id"], "thread_id": row["thread_id"],
                "story_id": values.get("story_id") or row["story_id"], "version": values.get("version"),
                "status": row["status"], "current_agent": values.get("current_agent", ""),
                "stages": [{"name": n, "status": stages_state.get(n, "pending")} for n in order],
                "token_usage": usage, "errors": values.get("errors", []), "retries": values.get("retries", 0),
                "workflow_type": row["workflow_type"], "created_at": row["created_at"],
                "updated_at": row["updated_at"], "awaiting": awaiting,
                "editorial_status": values.get("editorial_status"), "safety_status": values.get("safety_status"),
                "continuity_status": values.get("continuity_status"),
                "revision_attempts": values.get("revision_attempts", 0),
                "approval_status": values.get("approval_status"),
                "publishing_status": values.get("publishing_status"),
                "context_budget": values.get("context_budget", {})}

    def list(self, page: int = 1, page_size: int = 20) -> dict:
        page, page_size = max(1, int(page)), max(1, min(int(page_size), 200))
        rows, total = self.registry.list(page_size, (page - 1) * page_size)
        return {"items": [self.get(r["workflow_id"]) for r in rows], "total": total, "page": page,
                "page_size": page_size}

    async def events(self, workflow_id: str, poll_interval: float = 0.1, stop_when_idle: bool = False
                     ) -> AsyncIterator[dict]:
        """SSE-ready dict stream. Ends when the workflow reaches a terminal status (or, with
        ``stop_when_idle``, when it is waiting for a human)."""
        self._row(workflow_id)
        seq = 0
        if not self.ctx.events.known(workflow_id):  # e.g. after a restart: synthesise from the checkpoint
            yield {"seq": 0, "type": "snapshot", **self.get(workflow_id)}
        while True:
            status = self._row(workflow_id)["status"]   # read status BEFORE events so the last event is not missed
            evs = self.ctx.events.since(workflow_id, seq)
            for e in evs:
                seq = e["seq"]
                yield e
            if not evs and (status in TERMINAL or (stop_when_idle and status == "awaiting_human")):
                return
            await asyncio.sleep(poll_interval)

    def agent_status(self) -> list[dict]:
        from backend.agents import AGENT_CLASSES
        util = self.ctx.budget.stats().get("agents", {})
        out = []
        for c in AGENT_CLASSES:
            a = self.ctx.agents[c.agent_id]
            st = self.ctx.agent_stats.get(c.agent_id, {})
            out.append({"agent_id": c.agent_id, "status": "running" if st.get("active", 0) > 0 else "idle",
                        "uses_llm": c.uses_llm, "prompt_version": c.prompt_version,
                        "model_id": a.config.model_id if c.uses_llm else None,
                        "runs": st.get("runs", 0), "failures": st.get("failures", 0),
                        "last_run": st.get("last_run"), "input_tokens": st.get("input_tokens", 0),
                        "output_tokens": st.get("output_tokens", 0),
                        "context_utilisation": util.get(c.agent_id, {}).get("max_utilisation"),
                        "cache_namespace": c.cache_namespace, "allowed_tools": sorted(c.allowed_tools),
                        "context_policy": c.context_policy})
        return out

    def wait(self, workflow_id: str, timeout: float = 30.0) -> dict:
        """Block until the workflow stops running (finished or awaiting a human). Mainly for tests/CLI."""
        end = time.time() + timeout
        while time.time() < end:
            t = self._threads.get(workflow_id)
            if t is not None:
                t.join(timeout=max(0.0, min(0.2, end - time.time())))
            if self._row(workflow_id)["status"] != "running" and (t is None or not t.is_alive()):
                break
        return self.get(workflow_id)

    # -- internals -----------------------------------------------------------------------------------------------
    def _row(self, wid: str) -> dict:
        row = self.registry.get(wid)
        if row is None:
            raise WorkflowNotFound(wid)
        return row

    def _dispatch(self, wid: str, payload: Any) -> None:
        if self.inline:
            self._execute(wid, payload)
            return
        t = threading.Thread(target=self._execute, args=(wid, payload), daemon=True, name=f"wf-{wid}")
        self._threads[wid] = t
        t.start()

    def _execute(self, wid: str, payload: Any) -> None:
        row = self._row(wid)
        with self._lock(wid):
            try:
                self._graph(row["workflow_type"]).invoke(payload, self._cfg(row))
            except BaseException as exc:  # a crash leaves the checkpoint intact; recover_interrupted() continues it
                log.exception("workflow %s interrupted", wid)
                self.ctx.events.publish(wid, {"type": "workflow_status", "status": "interrupted",
                                              "detail": f"{type(exc).__name__}: {exc}"[:300]})
                self.registry.update(wid, status="interrupted")
                return
            self._sync(wid, row)

    def _sync(self, wid: str, row: dict) -> None:
        snap = self._graph(row["workflow_type"]).get_state(self._cfg(row))
        values = snap.values or {}
        waiting = [i.value for t in snap.tasks for i in t.interrupts]
        if snap.next and waiting:
            status, extra = "awaiting_human", {"awaiting": waiting[0]}
        else:
            status = values.get("status", "failed")
            if status == "running":
                status = "failed"  # graph ended without a terminal node: never report success implicitly
            extra = {}
        self.ctx.events.publish(wid, {"type": "workflow_status", "status": status, "story_id": values.get("story_id"),
                                      "version": values.get("version"), **extra})
        self.registry.update(wid, status=status, story_id=values.get("story_id"))


_service: WorkflowService | None = None
_service_lock = threading.Lock()


def get_workflow_service() -> WorkflowService:
    global _service
    with _service_lock:
        if _service is None:
            _service = WorkflowService()
        return _service


def reset_workflow_service(service: WorkflowService | None = None) -> None:
    global _service
    with _service_lock:
        _service = service
