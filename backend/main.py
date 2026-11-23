"""FastAPI application factory. Run: ``uvicorn backend.main:app --reload``."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend import database
from backend.api.errors import install_error_handlers
from backend.api.router import api_router
from backend.config import Settings, get_settings
from backend.utils.logging_setup import setup_logging

log = logging.getLogger("midnight.app")


def create_app(settings: Optional[Settings] = None, enable_scheduler: bool = True, llm=None,
               queue=None) -> FastAPI:
    """``llm`` / ``queue`` inject an LLMClient / PublishingQueueService (tests use fakes; never real publishing)."""
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        settings.validate_startup()  # raises ConfigurationError listing every problem: fail fast
        setup_logging(settings)
        database.configure(settings.database_url)
        database.init_db()
        from backend.runtime import build_runtime, install_runtime, uninstall_runtime
        rt = build_runtime(settings, queue=queue, llm=llm)  # ONE cache / budget / queue / workflow service for API + agents + scheduler
        app.state.runtime = rt
        app.state.cache = rt.cache
        app.state.context_budget = rt.budget
        app.state.publishing_queue = rt.queue
        app.state.workflow = rt.workflow
        install_runtime(rt)
        try:
            recovered = rt.workflow.recover_interrupted()
            if recovered:
                log.info("recovered interrupted workflows: %s", recovered, extra={"operation": "recover"})
        except Exception:  # noqa: BLE001 - a broken checkpoint must not stop the API from starting
            log.exception("workflow recovery failed", extra={"operation": "recover"})
        app.state.scheduler = None
        if enable_scheduler:
            from backend.automation.scheduler import SchedulerService
            app.state.scheduler = SchedulerService(settings, cache=app.state.cache, queue=rt.queue)
            app.state.scheduler.start()
        log.info("application started", extra={"operation": "startup"})
        try:
            yield
        finally:
            if app.state.scheduler is not None:
                app.state.scheduler.shutdown()
            uninstall_runtime()
            log.info("application stopped", extra={"operation": "shutdown"})

    app = FastAPI(title="The Midnight Files API", version="1.0.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.cache = None
    app.state.context_budget = None
    app.state.publishing_queue = None
    app.state.workflow = None
    app.state.scheduler = None
    app.add_middleware(CORSMiddleware, allow_origins=list(settings.cors_origins), allow_credentials=True,
                       allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"], allow_headers=["*"])
    install_error_handlers(app)
    app.include_router(api_router)
    return app


def _default_app() -> FastAPI:
    return create_app()


app = _default_app()
