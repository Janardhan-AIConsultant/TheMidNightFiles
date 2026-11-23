"""Workflow + publishing endpoints. Both delegate entirely to services owned elsewhere (lazy, 503 if absent)."""
from __future__ import annotations

import asyncio
import inspect
import json
from datetime import datetime
from typing import Any, AsyncIterator, Literal, Optional

from fastapi import APIRouter, Depends, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from starlette.concurrency import iterate_in_threadpool

from backend.api.common import Page, call, naive_utc, paginate_external, plain
from backend.api.deps import get_publishing_service_dep, get_workflow_service_dep
from backend.api.errors import ApiError, NotFound
from backend.services.approval_service import ApprovalError

router = APIRouter()


class WorkflowStart(BaseModel):
    """``params`` is merged FLAT into the WorkflowService request (stages, requested_word_count, story_type,
    platforms, topic, genre, version, ...). ``kind`` is accepted as an alias of ``workflow_type``."""
    workflow_type: Optional[str] = Field(default=None, max_length=60)
    kind: Optional[str] = Field(default=None, max_length=60)
    story_id: Optional[str] = None
    params: dict = Field(default_factory=dict)


class WorkflowResume(BaseModel):
    """Approval interrupt: {decision: approve|reject, approver, notes}. Human-review interrupt:
    {action: revise|rerun|reject, notes}. Exactly one of ``decision`` / ``action`` is required."""
    decision: Optional[Literal["approve", "reject"]] = None
    approver: Optional[str] = Field(default=None, max_length=100)
    action: Optional[Literal["revise", "rerun", "reject"]] = None
    notes: str = Field(default="", max_length=2000)


LEGACY_TYPES = {"story_pipeline": "story_generation"}


def build_start_request(workflow_type: Optional[str], story_id: Optional[str], params: dict) -> dict:
    """Shape the dict that WorkflowService.start(request) expects."""
    req = dict(params or {})
    wtype = workflow_type or req.get("workflow_type") or "story_generation"
    req["workflow_type"] = LEGACY_TYPES.get(wtype, wtype)
    if story_id:
        req["story_id"] = story_id
    return req


def workflow_view(d: Any) -> Any:
    """Add the aliases the UI reads (id, kind, steps, current_stage) without dropping any real field."""
    d = plain(d)
    if isinstance(d, dict) and "workflow_id" in d:
        d.setdefault("id", d["workflow_id"])
        d.setdefault("kind", d.get("workflow_type"))
        d.setdefault("steps", d.get("stages", []))
        d.setdefault("current_stage", next((s["name"] for s in d.get("stages", [])
                                            if s.get("status") in ("running", "awaiting_human")), None))
        if d.get("errors"):
            d.setdefault("error", str(d["errors"][-1].get("message", ""))[:300])
    return d


class QueueEnqueue(BaseModel):
    story_id: str
    version: int = Field(ge=1)
    platform: str = Field(pattern=r"^[a-z0-9_]{2,30}$")
    scheduled_for: Optional[str] = None


def _translate(exc: Exception) -> ApiError:
    """Map exceptions from external services to the error envelope without hiding domain meaning."""
    if isinstance(exc, ApiError):
        return exc
    name = type(exc).__name__
    msg = str(exc).lower()
    if name == "PublishingQueueError":
        if msg.startswith("unknown"):
            return ApiError(404, "not_found", str(exc))
        if msg.startswith("unsupported"):
            return ApiError(422, "invalid_request", str(exc))
        return ApiError(409, "approval_blocked" if "not publishable" in msg else "conflict", str(exc))
    if name == "WorkflowError":  # e.g. unknown workflow_type
        return ApiError(422, "invalid_request", str(exc))
    if isinstance(exc, ApprovalError) or "Approval" in name or "NotPublishable" in name:
        return ApiError(409, "approval_blocked", str(exc))
    if isinstance(exc, (KeyError, LookupError)) or "NotFound" in name:
        return ApiError(404, "not_found", str(exc).strip("'\""))
    if isinstance(exc, ValueError):
        return ApiError(422, "invalid_request", str(exc))
    if "Conflict" in name or "State" in name or "Stale" in name or "Duplicate" in name:
        return ApiError(409, "conflict", str(exc))
    raise exc


async def guarded(fn, *args, **kwargs):
    try:
        return await call(fn, *args, **kwargs)
    except ApiError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise _translate(exc) from exc


def _need(obj, *names):
    for n in names:
        fn = getattr(obj, n, None)
        if callable(fn):
            return fn
    raise ApiError(503, "service_unavailable", f"Service does not provide {names[0]}")


# ---------------------------------------------------------------- workflows
@router.get("/workflows")
async def list_workflows(p: Page = Depends(), status: Optional[str] = None, story_id: Optional[str] = None,
                         wf=Depends(get_workflow_service_dep)):
    res = plain(await guarded(_need(wf, "list", "list_workflows"), page=p.page, page_size=p.page_size))
    if isinstance(res, dict) and "items" in res:
        items = [workflow_view(i) for i in res["items"]]
        if status or story_id:  # WorkflowService has no filters: filter the returned page
            items = [i for i in items if (not status or str(i.get("status", "")).lower() == status.lower())
                     and (not story_id or i.get("story_id") == story_id)]
            res = {**res, "total": len(items)}
        return paginate_external({**res, "items": items}, p)
    return paginate_external(res, p)


@router.post("/workflows", status_code=202)
async def start_workflow(body: WorkflowStart, wf=Depends(get_workflow_service_dep)):
    request = build_start_request(body.workflow_type or body.kind, body.story_id, body.params)
    res = await guarded(_need(wf, "start"), request)
    if isinstance(res, str):  # WorkflowService.start returns the new workflow id
        getter = getattr(wf, "get", None)
        doc = await guarded(getter, res) if callable(getter) else None
        res = workflow_view(doc) if isinstance(doc, dict) else {"workflow_id": res, "id": res, "status": "running"}
    else:
        res = workflow_view(res)
    return JSONResponse(status_code=202, content=jsonable_encoder(res))


@router.get("/workflows/{workflow_id}")
async def get_workflow(workflow_id: str, wf=Depends(get_workflow_service_dep)):
    res = await guarded(_need(wf, "get", "get_workflow"), workflow_id)
    if res is None:
        raise NotFound(f"Workflow {workflow_id}")
    return workflow_view(res)


@router.post("/workflows/{workflow_id}/resume", status_code=202)
async def resume_workflow(workflow_id: str, body: WorkflowResume, wf=Depends(get_workflow_service_dep)):
    if (body.decision is None) == (body.action is None):
        raise ApiError(422, "validation_error", "provide exactly one of 'decision' (approval) or 'action' (review)")
    if body.decision:
        decision = {"decision": body.decision, "notes": body.notes}
        if body.decision == "approve":
            decision["approver"] = (body.approver or "operator").strip()
        elif body.approver:
            decision["approver"] = body.approver
    else:
        decision = {"action": body.action, "notes": body.notes}
    # WorkflowStateError (not awaiting) / StaleVersionError -> 409 via _translate; unknown id -> 404
    await guarded(_need(wf, "resume"), workflow_id, decision)
    getter = getattr(wf, "get", None)
    doc = await guarded(getter, workflow_id) if callable(getter) else None
    return JSONResponse(status_code=202, content=jsonable_encoder(
        workflow_view(doc) if isinstance(doc, dict) else {"workflow_id": workflow_id, "id": workflow_id}))


def _sse(event: dict, idx: int) -> str:
    name = str(event.get("type") or event.get("event") or "message") if isinstance(event, dict) else "message"
    return f"id: {idx}\nevent: {name}\ndata: {json.dumps(jsonable_encoder(event), default=str)}\n\n"


async def _event_stream(request: Request, source: Any) -> AsyncIterator[str]:
    idx = 0
    try:
        if inspect.isawaitable(source):
            source = await source
        if hasattr(source, "__aiter__"):
            it = source.__aiter__()
        elif isinstance(source, dict) or not hasattr(source, "__iter__"):
            it = iterate_in_threadpool(iter([source]))
        else:
            it = iterate_in_threadpool(iter(source))
        async for raw in it:
            if await request.is_disconnected():
                return
            idx += 1
            yield _sse(plain(raw), idx)
        yield "event: end\ndata: {}\n\n"
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001
        yield f"event: error\ndata: {json.dumps({'message': type(exc).__name__})}\n\n"


@router.get("/workflows/{workflow_id}/events")
async def workflow_events(workflow_id: str, request: Request, wf=Depends(get_workflow_service_dep)):
    fn = _need(wf, "events", "stream_events")
    getter = getattr(wf, "get", None) or getattr(wf, "get_workflow", None)
    if callable(getter) and await guarded(getter, workflow_id) is None:  # fail with 404 before streaming
        raise NotFound(f"Workflow {workflow_id}")
    try:
        source = fn(workflow_id) if not inspect.iscoroutinefunction(fn) else await fn(workflow_id)
    except Exception as exc:  # noqa: BLE001
        raise _translate(exc) from exc
    return StreamingResponse(_event_stream(request, source), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/agents/status")
async def agents_status(wf=Depends(get_workflow_service_dep)):
    res = plain(await guarded(_need(wf, "agent_status", "agents_status")))
    return res if isinstance(res, dict) and "items" in res else {"items": res if isinstance(res, list) else
                                                                  [{"agent": k, **(v if isinstance(v, dict) else {"status": v})}
                                                                   for k, v in (res or {}).items()]}


# ---------------------------------------------------------------- publishing queue
@router.get("/publishing/queue")
async def list_queue(p: Page = Depends(), status: Optional[str] = None, story_id: Optional[str] = None,
                     platform: Optional[str] = None, svc=Depends(get_publishing_service_dep)):
    kw = {k: v for k, v in {"status": status, "platform": platform, "story_id": story_id}.items() if v}
    res = await guarded(_need(svc, "list_jobs"), page=p.page, page_size=p.page_size, **kw)
    return paginate_external(res, p)


@router.post("/publishing/queue", status_code=201)
async def enqueue(body: QueueEnqueue, svc=Depends(get_publishing_service_dep)):
    when = None
    if body.scheduled_for:
        try:
            when = naive_utc(datetime.fromisoformat(body.scheduled_for.replace("Z", "+00:00")))
        except ValueError:
            raise ApiError(422, "validation_error", "scheduled_for must be an ISO-8601 datetime") from None
    res = await guarded(_need(svc, "enqueue"), story_id=body.story_id, version=body.version,
                        platform=body.platform, scheduled_at=when)
    return JSONResponse(status_code=201, content=jsonable_encoder(plain(res)))


@router.post("/publishing/queue/{job_id}/cancel")
async def cancel_job(job_id: int, svc=Depends(get_publishing_service_dep)):
    res = await guarded(_need(svc, "cancel"), job_id)
    return plain(res) if res is not None else {"id": job_id, "status": "CANCELLED"}


@router.post("/publishing/queue/{job_id}/retry")
async def retry_job(job_id: int, svc=Depends(get_publishing_service_dep)):
    res = await guarded(_need(svc, "retry"), job_id)
    return plain(res) if res is not None else {"id": job_id, "status": "PENDING"}
