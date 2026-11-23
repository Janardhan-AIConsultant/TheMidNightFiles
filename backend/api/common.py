"""Pagination, serialisation helpers, and the safe caller for external (lazy) services."""
from __future__ import annotations

import dataclasses
import enum
import inspect
from typing import Any, Callable

from fastapi import Query
from sqlalchemy import func, select
from sqlalchemy.inspection import inspect as sa_inspect
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

MAX_PAGE_SIZE = 200


class Page:
    def __init__(self, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=MAX_PAGE_SIZE)):
        self.page, self.page_size = page, page_size

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


def page_envelope(items: list, total: int, p: Page) -> dict:
    return {"items": items, "total": total, "page": p.page, "page_size": p.page_size}


def paginate(session: Session, stmt, p: Page, ser: Callable[[Any], dict]) -> dict:
    total = session.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    rows = session.scalars(stmt.limit(p.page_size).offset(p.offset)).all()
    return page_envelope([ser(r) for r in rows], total, p)


def row(obj: Any, exclude: tuple[str, ...] = ()) -> dict:
    out = {}
    for attr in sa_inspect(obj).mapper.column_attrs:
        if attr.key in exclude:
            continue
        key = "metadata" if attr.key == "story_metadata" else attr.key
        out[key] = getattr(obj, attr.key)
    return out


def plain(x: Any) -> Any:
    """Normalise whatever an external service returns into JSON-able data."""
    if x is None or isinstance(x, (str, int, float, bool)):
        return x
    if isinstance(x, enum.Enum):
        return x.value
    if hasattr(x, "model_dump"):
        return plain(x.model_dump())
    if dataclasses.is_dataclass(x) and not isinstance(x, type):
        return plain(dataclasses.asdict(x))
    if isinstance(x, dict):
        return {str(k): plain(v) for k, v in x.items()}
    if isinstance(x, (list, tuple, set)):
        return [plain(v) for v in x]
    if hasattr(x, "isoformat"):
        return x.isoformat()
    try:
        if sa_inspect(x, raiseerr=False) is not None:
            return plain(row(x))
    except Exception:
        pass
    if hasattr(x, "__dict__"):
        return plain({k: v for k, v in vars(x).items() if not k.startswith("_")})
    return str(x)


async def call(fn: Callable, *args, **kwargs) -> Any:
    """Call a sync or async service method without blocking the event loop."""
    if inspect.iscoroutinefunction(fn):
        res = await fn(*args, **kwargs)
    else:
        res = await run_in_threadpool(fn, *args, **kwargs)
    if inspect.isawaitable(res):
        res = await res
    return res


def paginate_external(result: Any, p: Page) -> dict:
    """Accept {items,total} or a list from an external service and apply paging if it did not."""
    result = plain(result)
    if isinstance(result, dict) and "items" in result:
        items = result["items"]
        total = result.get("total", len(items))
        if len(items) > p.page_size:
            items = items[p.offset:p.offset + p.page_size]
        return page_envelope(items, total, p)
    items = result if isinstance(result, list) else []
    return page_envelope(items[p.offset:p.offset + p.page_size], len(items), p)


def naive_utc(dt):
    """Aware datetimes are converted to UTC; naive ones are taken as UTC (DB stores naive UTC)."""
    from datetime import timezone
    return dt.astimezone(timezone.utc).replace(tzinfo=None) if dt.tzinfo else dt
