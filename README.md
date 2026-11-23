# The Midnight Files

Automation console for a horror-fiction publication: agents plan, write, humanise and review stories; a **human
approves every story version**; approved versions are handed to a Playwright-based publishing queue.
Backend: FastAPI + SQLAlchemy (SQLite) + LangGraph. Frontend: React + Vite (see `frontend/`).

## Architecture

```
React UI (frontend/)  --HTTP/SSE-->  FastAPI  /api/v1  (backend/api)
                                        |
        app.state: ONE CacheService, ONE ContextBudgetService, ONE PublishingQueueService,
                   ONE WorkflowService   (built in backend/runtime.py, wired in backend/main.py)
                                        |
   WorkflowService (LangGraph, SQLite checkpoints in data/checkpoints.db)
     story_generation: validate > planner > writer > humanise > continuity > editorial > safety
                       > (bounded auto-revision, then human_review interrupt) > images > distribution
                       > readiness > approval (human interrupt) > queue
     story_review / distribution / publishing: sub-graphs of the above
        |                         |                              |
   agents (backend/agents)   services (stories, reviews,    PublishingQueueService (backend/automation)
   all LLM calls via          approvals, cache, context        claim > re-validate every gate > Playwright
   LLMClient + budget check   budget, invalidation)            publisher > verify. APScheduler only triggers.
```

Key rules enforced in code: story text is immutable-versioned (`StoryService.add_revision`); editing creates a new
version and invalidates reviews, approvals and cache entries; only a named human can approve
(`ApprovalService`, the single eligibility gate -> HTTP 409 when blocked); queue jobs re-check every gate at
execution time; no log or agent-trace tables exist in the database (logs are rotating files in `logs/`).

Shared services: `backend/runtime.py` builds one cache / context-budget / queue / workflow service at startup, so
`/cache/stats`, `/context/stats` and `/dashboard/summary` reflect real agent usage. On startup
`WorkflowService.recover_interrupted()` continues workflows that were mid-run from their last checkpoint.

## API <-> workflow mapping

| Endpoint | WorkflowService call |
|---|---|
| `POST /api/v1/workflows {workflow_type\|kind, story_id?, params}` | `start({workflow_type, story_id, **params})` (`params`: `stages`, `requested_word_count`, `story_type`, `platforms`, `topic`, `genre`, ...). `story_pipeline` is accepted as an alias of `story_generation` |
| `POST /stories/{id}/humanise\|continuity\|editorial\|safety` | `start({workflow_type: "story_review", story_id, version, stages: [<kind>]})` |
| `POST /workflows/{id}/resume {decision, approver, notes}` | approval interrupt: `resume(id, {decision: approve\|reject, approver, notes})` |
| `POST /workflows/{id}/resume {action, notes}` | human-review interrupt: `resume(id, {action: revise\|rerun\|reject, notes})` |
| `GET /workflows`, `/workflows/{id}`, `/workflows/{id}/events` (SSE), `/agents/status` | `list`, `get`, `events`, `agent_status` |

Resume returns 409 when the workflow is not waiting or the story changed since the checkpoint (stale version),
404 for an unknown id, 422 for a malformed decision. Workflow documents also carry `id`, `kind`, `steps` and
`current_stage` aliases for the UI.

## Setup (Windows, PowerShell)

Requires Python 3.11 and Node 18+.

```powershell
cd "d:\substack automation\MidNightFiles"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m playwright install chromium     # only needed for real publishing
Copy-Item .env.example .env               # then edit .env: OPENAI_API_KEY, OPENAI_MODEL, ...
```

Secrets (`OPENAI_API_KEY`, `LANGSMITH_API_KEY`, `REDIS_URL`) live only in `.env` or the environment. `GET /settings`
only reports whether they are configured and never returns their values. All variables are documented in
`.env.example`. In `APP_ENV=production`, startup fails fast if `OPENAI_API_KEY`/`OPENAI_MODEL` are missing.

## Run

These are the exact commands (they are what the scripts run):

```powershell
.\scripts\start-backend.ps1                 # uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
.\scripts\start-backend.ps1 -Port 8000 -NoReload
.\scripts\start-frontend.ps1                # npm install (first run) + npm run dev -- --port 5173
.\scripts\start-frontend.ps1 -Install -ApiBaseUrl "http://localhost:8000/api/v1"
```

Health check: `Invoke-WebRequest http://127.0.0.1:8000/api/v1/health` (docs at `http://127.0.0.1:8000/docs`).
The database is created on first start (`data/substack_automation.db`); `alembic upgrade head` is also available.

## Tests

```powershell
.\scripts\run-tests.ps1                     # python -m pytest tests -q
.\scripts\run-tests.ps1 -Frontend           # also runs `npx vitest run` in frontend/
python -m pytest tests -q                   # same as the backend part
python -m pytest tests\integration\test_e2e.py -q   # API end-to-end with FakeLLMClient + mocked browser
```

Tests use fake LLM clients, temp databases and a mocked browser: they never call a real model and never publish.

## Image generation hook

No real image backend is bundled. Set `IMAGE_GENERATOR=package.module:callable` in `.env`; the callable receives
`(asset_spec: dict, story_id: str, version: int)` and must return a stored asset reference string. Without it the
Image agent only produces prompts, and the readiness gate stops the workflow with "no validated image assets".

## Limitations

- No image or video generation is included. YouTube and Instagram jobs additionally need a rendered `video_path`;
  without one they are BLOCKED at execution (never submitted). Substack needs only title/body.
- Reddit jobs are refused until the subreddit rules are acknowledged in the payload (publisher safety check).
- Real publishing drives a logged-in browser profile via Playwright; captchas/2FA stop the job with a manual
  fallback message. Selectors can break when destination sites change and are only verified against a fake site.
- LLM provider support is OpenAI only (`LLM_PROVIDER=openai`); context limits for unknown models fall back to
  conservative defaults. Token counts for non-OpenAI tokenizers are estimates.
- The Redis cache backend is not implemented (filesystem only). SQLite single-node only; the workflow event bus
  is in memory (after a restart the SSE stream starts from a checkpoint snapshot).
- Workflow list filters (`status`, `story_id`) apply to the returned page; the calendar scheduler does not
  forward a calendar row's free-text `story_type` as a story profile.
- Frontend lives in `frontend/` and was not modified as part of backend integration.
