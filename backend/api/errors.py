"""Consistent error envelope: {"error": {"code", "message", "details"}}."""
from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from backend.models.entities import ImmutableError
from backend.services.approval_service import ApprovalError
from backend.services.content_path_manager import AssetProtectedError, PathSecurityError
from backend.services.review_service import ReviewError
from backend.services.story_profile_service import UnsupportedStoryProfile
from backend.services.story_service import StoryError

log = logging.getLogger("midnight.app.api")


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, details: Any = None):
        self.status, self.code, self.message, self.details = status, code, message, details
        super().__init__(message)


def NotFound(what: str) -> ApiError:  # noqa: N802
    return ApiError(404, "not_found", f"{what} not found")


def ServiceUnavailable(message: str) -> ApiError:  # noqa: N802
    return ApiError(503, "service_unavailable", message)


def envelope(code: str, message: str, details: Any = None) -> dict:
    return {"error": {"code": code, "message": message, "details": details}}


def _resp(status: int, code: str, message: str, details: Any = None) -> JSONResponse:
    return JSONResponse(status_code=status, content=envelope(code, message, details))


_HTTP_CODES = {400: "bad_request", 401: "unauthorized", 403: "forbidden", 404: "not_found",
               405: "method_not_allowed", 409: "conflict", 422: "validation_error", 503: "service_unavailable"}


def _is_missing(msg: str) -> bool:
    return msg.startswith(("unknown story", "no revision"))


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api(_: Request, exc: ApiError):
        return _resp(exc.status, exc.code, exc.message, exc.details)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException):
        return _resp(exc.status_code, _HTTP_CODES.get(exc.status_code, "http_error"), str(exc.detail))

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError):
        details = [{"loc": [str(x) for x in e.get("loc", [])], "message": e.get("msg"), "type": e.get("type")}
                   for e in exc.errors()]
        return _resp(422, "validation_error", "Request validation failed", details)

    @app.exception_handler(ApprovalError)
    async def _approval(_: Request, exc: ApprovalError):
        return _resp(409, "approval_blocked", str(exc), {"reasons": [r.strip() for r in str(exc).split(";")]})

    @app.exception_handler(StoryError)
    async def _story(_: Request, exc: StoryError):
        m = str(exc)
        return _resp(404 if _is_missing(m) else 422, "not_found" if _is_missing(m) else "invalid_story", m)

    @app.exception_handler(ReviewError)
    async def _review(_: Request, exc: ReviewError):
        m = str(exc)
        return _resp(404 if _is_missing(m) else 422, "not_found" if _is_missing(m) else "invalid_review", m)

    @app.exception_handler(UnsupportedStoryProfile)
    async def _profile(_: Request, exc: UnsupportedStoryProfile):
        return _resp(422, "unsupported_story_profile", str(exc))

    @app.exception_handler(PathSecurityError)
    async def _path(_: Request, exc: PathSecurityError):
        return _resp(400, "invalid_path", "Invalid identifier or path")

    @app.exception_handler(ImmutableError)
    async def _immutable(_: Request, exc: ImmutableError):
        return _resp(409, "immutable", str(exc))

    @app.exception_handler(AssetProtectedError)
    async def _asset(_: Request, exc: AssetProtectedError):
        return _resp(409, "asset_protected", str(exc))

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception):
        log.error("unhandled error: %s", type(exc).__name__, exc_info=exc)
        return _resp(500, "internal_error", "Internal server error")
