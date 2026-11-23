# The Midnight Files — Project Plan & Shared Contracts

Source spec: `implementation.md` (read only the sections your task names).
Root (confirmed by user; overrides the spec's `D:\substack automation`): `d:\substack automation\MidNightFiles`. Greenfield: nothing pre-existed (assessed 2026-11-24).
Python 3.11, Windows. Installed: fastapi, sqlalchemy 2, alembic, pydantic 2, pydantic-settings, apscheduler, langchain, langsmith, playwright, pytest, httpx. langgraph may need `pip install`.

## Rules for all agents
- Edit ONLY your owned paths. Do not touch others' files; import their public APIs per the contracts below.
- No mocks replacing real logic; LLM calls go through an injectable `LLMClient` protocol so tests use fakes.
- No logs/agent-traces tables in SQLite. No secrets in code. Never publish for real in tests.
- Add tests under `tests/`; run them with `python -m pytest <your tests> -q`. Report only: files created, test result line, known gaps (<=15 lines).

## Package layout
backend/{config.py, database.py, main.py, models/, schemas/, api/, agents/, orchestration/, cache/, services/, publishers/, automation/, utils/}
data/{content,cache,exports,backups}, logs/, prompts/, tests/{unit,integration,workflows,cache,publishing}, frontend/

## Public contracts (owners implement exactly these names)

### Owner A — infrastructure (`backend/config.py`, `backend/cache/`, `backend/services/{cache_service,cache_key_service,cache_invalidation_service,cache_cleanup_service,context_budget_service,model_registry,story_profile_service,chunking_service}.py`, `backend/utils/logging_setup.py`)
- `config.get_settings() -> Settings` (pydantic-settings; all env vars in spec §19 + `MAX_REVISION_ATTEMPTS`, `PUBLISHING_MAX_RETRIES`, `DATA_DIR`, `LOG_DIR`, `LLM_PROVIDER`, `CORS_ORIGINS`); `Settings.validate_startup()`.
- `CacheService`: `get(namespace,key)`, `set(namespace,key,value,ttl=None)`, `get_or_compute(namespace,key,fn,validate=None,ttl=None)` (single-flight, fail-open, rejects corrupt), `invalidate_story(story_id, from_version=None)`, `stats() -> {hits,misses,errors,size_mb,by_namespace}`; `build_key(**parts)->sha256 of canonical JSON`.
- `ModelRegistry.get(model_id)->ModelSpec(provider,model_id,context_limit,max_output,tools,structured,pricing|None)`; unknown → conservative default (documented).
- `ContextBudgetService.plan(agent_id, model_id, system_tokens, agent_tokens, convo_tokens, expected_output) -> BudgetPlan(available_input, reserved_output, safety_margin, fits)`; `estimate_tokens(text,model_id)`; `ensure_fits(...)` raises `ContextOverflowError`; records utilisation stats via `.stats()`.
- `select_story_profile(story_type, requested_word_count, platform, series_mode) -> StoryProfile` (spec §7 fields + defaults table; honours requested count within limits, raises on unsupported).
- `ChunkingService.chunk(text, story_id, version, max_tokens, overlap)->list[Chunk(id,index,start,end,text,hash)]`, `reassemble(chunks)->str`, `validate_reassembly(original, chunks)` (no missing/duplicate paragraphs).
- `utils.logging_setup.setup_logging(settings)`: rotating files app/agent/publishing/scheduler/error, JSON lines, secret redaction filter.

### Owner B — persistence & story management (`backend/database.py`, `backend/models/`, `alembic/`, `alembic.ini`, `backend/services/{content_path_manager,story_service,approval_service,series_service,summary_service,review_service}.py`, `backend/schemas/`)
- SQLAlchemy models for spec §11 entities (stories, story_revisions, story_series, series_continuity, images, distribution_content, publishing_queue, publishing_history, scheduled_tasks, platform_accounts, analytics, content_approvals, content_safety_reviews, editorial_reviews, humanisation_reviews, content_calendar, topic_history, settings, summaries). NO log tables. Alembic initial migration. `database.get_session()` contextmanager / FastAPI dependency; `init_db()`.
- `ContentPathManager(root)`: `story_dir(story_id)`, `revision_path(story_id,version,name)`, `asset_path(...)`, atomic write, traversal prevention, extension allowlist, never overwrite/delete referenced assets.
- `StoryService`: `create_story(...)->Story`, `add_revision(story_id, text, kind, author)->Revision` (immutable, version+1, sha256 hash, invalidates reviews/approvals via callback `on_new_version(story_id, version)` injected so Owner A's cache can hook in), `get_revision(story_id, version=None)`, `list_revisions`.
- `ReviewService.record_editorial/ record_continuity/ record_safety(story_id, version, status, findings, coverage)`; safety `PASSED` requires `coverage == 1.0`; statuses per spec §4.
- `ApprovalService.approve(story_id, version, approver)` — requires editorial APPROVED + safety PASSED for that exact version, else `ApprovalError`; `is_publishable(story_id, version)->(bool, reasons)`; approvals bound to review IDs; auto-invalid on new version.
- `SeriesService` (versioned series bible), `SummaryService` (records source id/version/hash/prompt version/model/deps; invalidates on dependency change).

### Owner C — frontend (`frontend/` only)
React18+TS+Vite+Tailwind+shadcn-style components+Lucide+React Router+TanStack Query+Zustand+RHF+Zod+Axios+Recharts+FullCalendar+Sonner; Vitest+RTL. Dark cinematic theme (charcoal/near-black, restrained crimson). 11 pages per spec §13. All data from API `VITE_API_BASE_URL` (default `http://localhost:8000/api/v1`); no hardcoded metrics; loading/empty/error states.

### API contract (`/api/v1`, FastAPI owner D implements; frontend consumes) — JSON, paginated lists = `{items,total,page,page_size}`
GET /dashboard/summary · GET/POST /calendar, PATCH /calendar/{id} (reschedule) · GET/POST /stories, GET/PATCH /stories/{id}, GET /stories/{id}/revisions, POST /stories/{id}/revisions, GET /story-profiles, POST /stories/{id}/humanise|continuity|editorial|safety (start workflow) · GET /reviews?story_id= · POST /approvals {story_id,version,decision,notes}, GET /approvals/pending · GET /safety/reviews · GET /publishing/queue, POST /publishing/queue, POST /publishing/queue/{id}/cancel|retry · GET/PUT /distribution/{story_id}/{platform} · GET /workflows, GET /workflows/{id}, GET /workflows/{id}/events (SSE), POST /workflows · GET /agents/status · GET /analytics/summary, /analytics/stories · GET /logs?channel=&level=&limit= · GET/PUT /settings (secrets masked) · GET /health, /cache/stats, /context/stats.
Errors: `{error:{code,message,details}}`.

### Owner D — agents/orchestration/API/publishing/scheduler (wave 2, after A and B exist)
`backend/agents/*` (BaseAgent with Pydantic in/out, prompt versions in `prompts/`, budget, timeout, retry, cache, LangSmith tracing wrapper that fails open), `backend/orchestration/*` per spec §5 with SQLite-file LangGraph checkpointer (`data/checkpoints.db`, separate from business DB), `backend/api/*` + `backend/main.py`, `backend/publishers/*` + `backend/automation/*` (mock-browser-testable), APScheduler (Asia/Kolkata).

## Phases / waves
1. Wave 1 (parallel): A, B, C. 2. Wave 2 (parallel, split D into D1 agents+orchestration, D2 API+scheduler, D3 publishers+automation). 3. Wave 3: integration tests, docs (README, .env.example, scripts/*.ps1 startup), final report.
