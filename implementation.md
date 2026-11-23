# THE MIDNIGHT FILES

## Master Implementation Specification

**Purpose:** Complete implementation brief for Claude Code to inspect,
enhance and complete the existing The Midnight Files project without
destroying existing functionality, code, data, integrations or user
work.

------------------------------------------------------------------------

# 1. Project Overview

## Project name

**The Midnight Files**

## Tagline

"Some doors should never be opened. Some stories should never be told."

## Business objective

Build an AI-powered horror content creation and publishing platform
capable of:

1.  Planning horror content.
2.  Generating original horror stories.
3.  Humanising drafts through editorial refinement.
4.  Maintaining continuity across serialized stories.
5.  Reviewing editorial quality.
6.  Performing global safety and factual reviews.
7.  Generating cinematic story images.
8.  Preparing platform-specific distribution content.
9.  Managing human approvals.
10. Scheduling and publishing content.
11. Tracking publishing performance.
12. Monitoring AI agents, token usage, latency and operational health.

The platform targets a global adult English-speaking readership,
particularly the United States, United Kingdom, Canada and Australia.

## Editorial positioning

Focus on: - Psychological horror. - Supernatural horror. - Paranormal
mysteries. - Haunted locations. - Suspense and mystery. - Dark
fiction. - Serialized horror. - Folklore-inspired fiction. - Atmospheric
storytelling. - Unexpected and emotionally memorable endings.

Editorial principle:

> Make readers afraid of what might be hiding in the darkness, not
> uncomfortable because of irresponsible storytelling.

Stories must be original, immersive, emotionally authentic and
professionally edited. Avoid gratuitous gore, shock value, stereotypes,
cultural disrespect, defamatory claims, exploitative content and
misleading factual assertions.

Clearly distinguish original fiction from documented history, folklore
and real-world claims. Do not imitate the distinctive style of living
authors or use protected characters and story worlds without
authorisation.

Position the publication for adults aged 18+ without claiming formal age
certification.

------------------------------------------------------------------------

# 2. First Task: Inspect the Existing Project

Before writing or modifying code, inspect the entire existing
repository.

Expected project location:

`D:\substack automation`

Verify the actual working directory before proceeding. Never assume the
path is correct.

Inspect: - Existing folder structure. - Python files. - React or
Streamlit frontend. - FastAPI endpoints. - Existing agents. - LangChain
and LangGraph implementations. - Existing prompts. - Database models and
migrations. - SQLite records. - Existing story files. - Images and
videos. - Publishing integrations. - Playwright browser automation. -
Scheduler. - Cache implementations. - Environment variables. -
Logging. - Tests. - Documentation. - Installed dependency versions.

Create an architecture assessment document before making changes.
Document:

1.  Existing functionality.
2.  Existing architecture.
3.  Existing APIs.
4.  Existing database schema.
5.  Existing agents and responsibilities.
6.  Existing content storage.
7.  Existing integrations.
8.  Missing functionality.
9.  Technical debt.
10. Migration risks.

Then create a phased implementation plan.

## Non-negotiable preservation rules

-   Do not delete existing working code without a documented reason.
-   Do not overwrite existing prompts without preserving their contents.
-   Do not delete existing stories, revisions, images, videos or
    publishing records.
-   Do not reset the database.
-   Do not recreate existing database tables unnecessarily.
-   Do not break existing API routes.
-   Do not break existing publishing integrations.
-   Do not remove working agent capabilities.
-   Do not remove existing safeguards.
-   Do not replace working implementations with mocks.
-   Do not downgrade dependencies without justification.
-   Do not perform destructive migrations.
-   Do not move content files without updating and validating every
    reference.
-   Do not expose or overwrite secrets.
-   Do not silently change existing business rules.

Use backward-compatible migrations and incremental changes. When an
existing implementation already satisfies a requirement, reuse it rather
than creating a duplicate service.

------------------------------------------------------------------------

# 3. Final Technology Architecture

  -----------------------------------------------------------------------
  Layer                   Technology              Responsibility
  ----------------------- ----------------------- -----------------------
  Frontend                React.js 18+            User interface

  Frontend language       TypeScript              Type safety

  Build tool              Vite                    Frontend development
                                                  and build

  CSS                     Tailwind CSS            Styling

  UI components           shadcn/ui               Consistent UI

  Icons                   Lucide React            Icons

  Routing                 React Router            Page navigation

  Server state            TanStack Query          API state and
                                                  client-side server
                                                  cache

  Client state            Zustand                 Lightweight client
                                                  state

  Forms                   React Hook Form + Zod   Form validation

  HTTP                    Axios                   API integration

  Charts                  Recharts                Analytics

  Calendar                FullCalendar or         Editorial calendar
                          suitable React calendar 

  Backend                 FastAPI                 API and business logic

  Agent orchestration     LangGraph               Multi-agent workflows

  Agent framework         LangChain + Python      Individual agents and
                                                  LLM integration

  Agent contracts         Pydantic                Structured inputs and
                                                  outputs

  Context management      Custom                  Token and context
                          ContextBudgetService    control

  Caching                 Shared                  Reusable computation
                          filesystem-backed cache 

  Future distributed      Redis                   Shared cache and
  cache                                           distributed
                                                  coordination

  Database                SQLite + SQLAlchemy     Business data

  Migrations              Alembic                 Schema evolution

  Workflow persistence    LangGraph-compatible    Workflow recovery
                          persistent checkpointer 

  Observability           LangSmith               AI execution tracing

  Browser automation      Playwright              Publishing

  Scheduler               APScheduler             Scheduled workflows

  Operational logging     Python rotating file    Application logs
                          handlers                

  Testing                 pytest, Vitest, React   Automated testing
                          Testing Library         
  -----------------------------------------------------------------------

## Important architecture decisions

### A. LangGraph is the central orchestrator

Use LangGraph to orchestrate all multi-agent workflows. LangChain should
be used for individual LLM interactions, prompts, structured output and
appropriate tools.

Do not use independent direct Python calls as the primary multi-agent
orchestration mechanism. Agents must not independently invoke other
agents to construct workflows.

LangGraph controls execution, state transitions, conditional routing,
retries, checkpoints and human approval interruptions.

APScheduler triggers workflows but does not replace LangGraph
orchestration.

### B. React is the only active frontend

Replace Streamlit with React + TypeScript + Tailwind CSS. FastAPI
remains the backend and sole business-logic layer.

React must communicate with FastAPI through APIs. Do not move agent
execution, database logic, publishing decisions or approval rules into
React.

Do not retire Streamlit until React has reproduced and passed
verification of the existing frontend functionality.

### C. Separate business data, workflow state, cache and logs

Keep these responsibilities separate:

-   SQLite: business records.
-   Filesystem cache: reusable computed outputs.
-   LangGraph checkpointer: workflow recovery and state.
-   LangSmith: AI execution traces and token observability.
-   Rotating files: operational and application logs.
-   Content folders: story assets and generated files.

Do not store agent execution logs or application logs in SQLite.

### D. Agent-specific context

Do not send every agent the same complete story and conversation
history. Every agent receives the smallest sufficient context required
for its task, without sacrificing correctness, editorial quality or
safety.

### E. Human-controlled publishing

No story may be published without passing the required review gates and
receiving explicit human approval for its exact version.

------------------------------------------------------------------------

# 4. Agent Architecture

Create modular, independently testable agents.

Each agent must have: - A single clear responsibility. - Pydantic input
schema. - Pydantic output schema. - Prompt template with versioning. -
Configurable model. - Input validation. - Output validation. - Token
budget. - Context policy. - Execution timeout. - Retry policy. -
Appropriate cache integration. - Restricted tools. - Explicit stop
conditions. - Structured error handling. - LangSmith tracing.

Agents must not have unrestricted database, filesystem, administrative
or publishing access. No agent can approve itself, override safety
decisions or bypass workflow gates.

## Agent 1: Content Planner

Responsibilities: - Generate a configurable 60-day editorial calendar. -
Recommend daily story topics. - Maintain genre diversity. - Prevent
unnecessary topic repetition. - Identify standalone and serialized
opportunities. - Track previous story topics. - Recommend publishing
dates. - Generate story metadata. - Consider platform requirements.

Output: - Story idea. - Working title. - Genre and subgenre. - Story
type. - Target word count. - Target audience. - Hook. - Synopsis. -
Characters. - Setting. - Planned date. - Series association. - Platform
opportunities.

## Agent 2: Horror Writer

Responsibilities: - Generate original horror stories. - Follow the
selected story-length profile. - Create compelling opening hooks. -
Develop believable characters. - Use natural dialogue. - Build
escalating tension. - Maintain narrative consistency. - Introduce
meaningful clues. - Deliver logical twists. - Produce memorable endings.

The writer must follow the approved creative brief. Do not allow the
writer to silently shorten stories.

## Agent 3: Humanisation Editor

Responsibilities: - Improve natural English. - Improve dialogue
authenticity. - Improve emotional depth. - Vary sentence structures. -
Improve paragraph rhythm. - Improve pacing. - Strengthen atmosphere. -
Remove unnecessary repetition. - Improve transitions. - Preserve plot,
clues, characters and meaning.

Humanisation is an editorial-quality process, not a mechanism for
evading AI detectors or misrepresenting authorship.

It must preserve plot, character identities and relationships, important
clues, timeline, story length requirements, supernatural rules and
narrative intent.

For long stories, process coherent chunks and reassemble them in the
correct order.

## Agent 4: Continuity Reviewer

Check: - Character names and ages. - Relationships. - Physical
descriptions. - Locations. - Timeline. - Objects. - Character
knowledge. - Events. - Supernatural rules. - Plot contradictions. -
Unresolved mysteries. - Cross-episode consistency.

Maintain a versioned series bible containing characters, relationships,
locations, timelines, important objects, supernatural rules, past
events, unresolved mysteries and established facts.

The continuity reviewer must receive the current story and only the
relevant series context.

## Agent 5: Editorial Reviewer

Review: - Originality. - Opening hook. - Story structure. - Suspense. -
Engagement. - Character development. - Dialogue. - Pacing. -
Atmosphere. - Twists. - Ending. - Grammar. - Readability. -
Repetition. - Narrative consistency. - Audience suitability.

For long stories, review the complete narrative using a suitable
multi-stage strategy. A synopsis alone is never sufficient for final
editorial approval.

Possible statuses: - `APPROVED` - `NEEDS_REVISION` -
`HUMAN_REVIEW_REQUIRED` - `REJECTED`

Every finding must include severity, issue, relevant passage or
location, explanation and recommended correction.

## Agent 6: Global Safety and Factual Reviewer

Review: - Cultural and religious sensitivity. - Stereotypes. - Racism. -
Xenophobia. - Graphic violence. - Sexual exploitation. - Sexualised
minors. - Sexual violence. - Self-harm. - Instructions enabling
wrongdoing. - Defamation. - Private information. - Misleading medical or
psychological advice. - Copyright and originality. - Misleading
headlines. - Platform suitability. - Unsupported real-world claims.

Statuses: - `NOT_REVIEWED` - `REVIEWING` - `PASSED` - `NEEDS_REVISION` -
`HUMAN_REVIEW_REQUIRED` - `BLOCKED`

Rules: - Every required section of the story must be reviewed. -
Incomplete coverage cannot receive `PASSED`. - Serious uncertainty must
be escalated to human review. - Critical safety findings must block
publication. - AI quality scores cannot override safety decisions. -
Safety review must be repeated after relevant story edits.

## Agent 7: Image Generation Agent

Generate original cinematic visual assets: - Story covers. - Article
images. - YouTube thumbnails. - Instagram promotional images.

Requirements: - Follow the story's visual direction. - Maintain
character appearance consistency. - Use appropriate aspect ratios. -
Create atmospheric cinematic compositions. - Save images in the correct
story folder. - Record image metadata. - Track source story version. -
Validate assets before distribution.

Do not overwrite existing referenced or published images.

## Agent 8: Distribution Agent

Generate separate platform-specific content from the approved story.

### Substack

-   Article title.
-   Subtitle.
-   Full article body.
-   Cover image reference.
-   SEO title and description.
-   Tags.
-   Notes content.
-   Engagement question.
-   Free/premium recommendation.

### YouTube Shorts

-   Opening hook.
-   Narration.
-   Script.
-   Scene breakdown.
-   Captions.
-   On-screen text.
-   Suggested duration.
-   Video title.
-   Description.
-   Hashtags.
-   Thumbnail reference.

### Instagram Reels

-   Opening hook.
-   Reel script.
-   Narration.
-   Scene breakdown.
-   Captions.
-   On-screen text.
-   Description.
-   Hashtags.
-   Cover image reference.

### Reddit

-   Post title.
-   Post body.
-   Discussion question.
-   Suitable subreddit recommendations.
-   Community-rule considerations.

Respect subreddit rules and avoid spam. Do not automatically post to
communities without validating the destination and applicable rules.

## Agent 9: Publishing Agent

Responsibilities: - Validate distribution payloads. - Validate story
version. - Validate review status. - Validate approval. - Validate
assets. - Validate schedule. - Validate publishing configuration. -
Create publishing queue jobs. - Track publishing results.

The publishing agent prepares and validates jobs. A separate Playwright
publishing worker performs browser interactions.

## Agent 10: Analytics Agent

Track actual available metrics: - Views. - Reads. - Likes. - Comments. -
Shares. - Subscribers. - Click-through rate. - Watch time. - Completion
rate. - Engagement. - Story performance.

Do not fabricate unavailable metrics. Clearly identify missing data.

------------------------------------------------------------------------

# 5. LangGraph Workflow Orchestration

Create a modular LangGraph architecture.

Suggested structure:

``` text
backend/orchestration/
    __init__.py
    graph_builder.py
    graph_state.py
    workflow_config.py
    workflow_registry.py
    checkpoint_manager.py
    workflow_router.py

    nodes/
        validation_node.py
        planner_node.py
        writer_node.py
        humanisation_node.py
        continuity_node.py
        editorial_node.py
        safety_node.py
        image_node.py
        distribution_node.py
        approval_node.py
        publishing_node.py
        analytics_node.py

    routers/
        editorial_router.py
        safety_router.py
        workflow_router.py

    workflows/
        story_generation_graph.py
        story_review_graph.py
        distribution_graph.py
        publishing_graph.py
```

Adapt to the existing folder structure.

## Main workflow

``` text
Content Request
      |
      v
Input Validation
      |
      v
Content Planner
      |
      v
Horror Writer
      |
      v
Humanisation Editor
      |
      v
Continuity Reviewer
      |
      v
Editorial Reviewer
      |
      +---- NEEDS_REVISION ----> Relevant Revision Node
      |                              |
      |                              v
      |                         Fresh Review
      |
      +---- HUMAN_REVIEW_REQUIRED --> Human Review
      |
      +---- REJECTED -------------> Terminate
      |
      v
Safety Reviewer
      |
      +---- NEEDS_REVISION ----> Revision + Fresh Review
      |
      +---- HUMAN_REVIEW_REQUIRED --> Human Review
      |
      +---- BLOCKED ------------> Terminate
      |
      v
Image Generation
      |
      v
Distribution
      |
      v
Publishing Readiness Validation
      |
      v
Human Approval
      |
      v
Publishing Queue
      |
      v
Playwright Publishing Worker
      |
      v
Publication Verification
      |
      v
Analytics
```

## Conditional routing

Editorial decisions: - `APPROVED`: proceed to safety. -
`NEEDS_REVISION`: route to the appropriate revision step. -
`HUMAN_REVIEW_REQUIRED`: interrupt for human review. - `REJECTED`:
terminate.

Safety decisions: - `PASSED`: proceed. - `NEEDS_REVISION`: revise and
rerun applicable reviews. - `HUMAN_REVIEW_REQUIRED`: interrupt for human
review. - `BLOCKED`: terminate.

Start with a configurable maximum of three automated revision attempts.
Prevent infinite loops.

Every revision creates a new story version and invalidates affected
downstream reviews.

## Workflow state

Use typed, serialisable state. Include: - Workflow ID and thread ID. -
Story ID and story version. - Content profile. - Creative brief. - Story
content reference and hash. - Synopsis. - Series context reference. -
Agent results. - Review statuses. - Safety status. - Image references. -
Distribution references. - Approval status and approval version. -
Publishing status. - Retry count. - Error summary. - Context budget. -
Token usage summary.

Do not duplicate entire large stories throughout graph state. Store
large content externally and pass stable references and hashes.

## Checkpointing and recovery

Implement persistent LangGraph-compatible checkpointing.

Requirements: - Resume interrupted workflows. - Recover from application
restarts. - Support human approval interruption. - Resume using the
correct workflow thread. - Prevent stale story versions from resuming
into publishing. - Separate checkpoints from cache entries.

Do not use in-memory checkpointing as the production persistence
strategy.

------------------------------------------------------------------------

# 6. Agentic Design Principles

Apply strong agent engineering principles.

## Single responsibility

Each agent must perform one clearly defined job.

## Structured communication

Use Pydantic schemas rather than unstructured agent-to-agent messages.

## Explicit tool permissions

Examples: - Planner: topic history and calendar tools. - Writer:
approved creative brief and relevant series context. - Humanisation:
story read/write revision services. - Continuity: story and series-bible
read access. - Editorial: story and editorial criteria. - Safety:
required story content and safety policies. - Image: approved story
context and image generation. - Distribution: approved story and
platform specifications. - Publishing: validated publishing queue
services. - Analytics: permitted metrics and analytics services.

No unrestricted access to the operating system, database, credentials or
publishing controls.

## Bounded reflection

Agents may validate their own structured output, but reflection must be
bounded.

Define maximum retries, revision attempts, tool calls, execution time,
input tokens, output tokens and terminal failure conditions.

Do not allow uncontrolled recursive agent execution.

## Evidence-based reviews

Review agents must cite the relevant story passage, section or
paragraph. Do not return vague findings without explanation and
actionable recommendations.

## Failure handling

Use structured errors and explicit retry policies. Distinguish
validation errors, context overflow, rate limits, model errors, tool
errors, cache errors, workflow errors and publishing errors.

Do not convert failed execution into an approval.

------------------------------------------------------------------------

# 7. Dynamic Story-Length Profiles

Implement a central story-profile service.

Initial configurable defaults:

  Profile                Target words   Permitted range
  -------------------- -------------- -----------------
  Micro Horror                    100           75--150
  Flash Fiction                   500          400--600
  Short Horror                  1,000        800--1,200
  Standard Horror               1,250      1,000--1,500
  Long Horror                   2,000      1,500--2,500
  Premium Feature               2,500      2,000--3,000
  Serialized Episode            1,500      1,000--2,000

These are initial defaults, not hardcoded universal limits.

The user's explicit requested word count takes priority within
configured supported limits. Do not silently turn a requested 2,500-word
story into a 1,000-word story.

Implement a central function:

`select_story_profile(story_type, requested_word_count, platform, series_mode)`

Return: - Profile name. - Target word count. - Minimum word count. -
Maximum word count. - Narrative structure. - Chapter count. - Writer
output budget. - Humanisation budget. - Continuity budget. - Editorial
budget. - Safety budget. - Synopsis budget. - Platform-specific
adaptation requirements.

Do not duplicate story-length rules across agents.

Platform adaptations must be separate deliverables. Never truncate the
original story to satisfy a platform's shorter content format.

------------------------------------------------------------------------

# 8. Context Budget Management

Implement a shared `ContextBudgetService`. This is a mandatory shared
service used before every LLM call.

Responsibilities: - Model context-window management. - Input token
estimation. - Output token reservation. - Prompt overhead accounting. -
Tool response allowance. - Context compression. - Relevant context
retrieval. - Chunking. - Summary generation. - Token safety margins. -
Agent-specific budgets.

## Context budget formula

Available input budget:

Model context window\
minus system instructions\
minus agent instructions\
minus conversation context\
minus expected output reservation\
minus tool-response reservation\
minus safety margin.

Never exceed the model's configured context limit. Reserve output tokens
before making a model call.

## Model capability registry

Maintain configurable model metadata: - Provider. - Model ID. - Context
limit. - Maximum output tokens. - Tool support. - Structured output
support. - Pricing configuration where verified.

Do not invent context limits or prices. If a model's capability is
unknown, use a conservative configurable limit and document the
assumption.

Use the actual tokenizer when supported. If exact tokenisation is
unavailable, use a conservative estimator and document its limitations.
Do not assume one universal words-to-token conversion.

## Agent-specific context policies

### Planner

Receives editorial calendar, topic history, audience preferences and
story requirements. Does not receive complete historical stories
unnecessarily.

### Writer

Receives creative brief, story-length profile, required narrative
elements and relevant series context.

### Humanisation

Receives the full story when possible; otherwise coherent chunks,
adjacent narrative context and relevant continuity constraints.

### Continuity

Receives current story, relevant series bible, character relationships,
timeline, locations, important objects, established supernatural rules
and relevant unresolved mysteries.

### Editorial

Receives the complete story when within budget. Otherwise receives
structured chunks, overall synopsis and narrative structure, and
relevant previous findings. A synopsis alone cannot replace the story
for final editorial review.

### Safety

Receives all required story content. If chunking is necessary, review
every required chunk, preserve chunk IDs, aggregate findings, perform
cross-section checks and verify complete coverage. Partial coverage
cannot receive `PASSED`.

### Image generation

Receives synopsis, important scenes, character appearance references,
atmosphere, visual direction and image format.

### Distribution

Receives approved story version, relevant platform requirements,
approved metadata and relevant image references.

### Analytics

Receives actual metrics, relevant period, platform ID and story ID. Do
not provide unrelated story context.

## Long-story chunking

Implement paragraph-aware, scene-aware and chapter-aware chunking.

Requirements: - Stable chunk IDs. - Source positions. - Controlled
overlap. - Story version and content hash. - Correct ordering. - No
missing paragraphs. - No duplicate paragraphs. - Reassembly validation.

Humanisation must preserve dialogue, clues, narrative continuity and
final length.

Editorial and safety reviews must account for the complete story.

## Summary management

Support: - Synopsis. - Character summary. - Series bible. - Scene
summary. - Continuity findings. - Editorial findings. - Safety
findings. - Distribution summary.

Every summary must record source story ID, source version, source hash,
prompt version, model ID, creation timestamp and dependency hashes.

Invalidate summaries when their dependencies change.

Summaries are context optimisation tools, not substitutes for original
content when complete review is required.

------------------------------------------------------------------------

# 9. Shared Caching Architecture

Caching is mandatory. Implement a shared cache architecture that every
suitable agent and service can use.

Do not create separate unrelated cache implementations for individual
agents.

## Recommended initial architecture

-   Filesystem-backed cache.
-   Shared `CacheService`.
-   Backend abstraction.
-   Redis-compatible future interface.
-   Cache invalidation service.
-   Cache cleanup service.
-   Cache key service.
-   Concurrency protection.

Suggested structure:

``` text
backend/cache/
    __init__.py
    base.py
    filesystem_backend.py
    redis_backend.py
    cache_models.py
    cache_registry.py

backend/services/
    cache_service.py
    cache_key_service.py
    cache_invalidation_service.py
    cache_cleanup_service.py
```

Implement only what is necessary. Redis support can remain an optional
future backend unless distributed deployment is already required.

## Cache key design

Use SHA-256 over canonical JSON.

Include relevant dependencies: - Agent identifier and version. - Prompt
template version/hash. - Input content hash. - Story ID and version. -
Series context hash. - Model provider. - Model identifier. - Model
parameters. - Output schema version. - Safety policy version where
relevant. - Relevant configuration.

Never hash the entire LangGraph state. Build keys from the specific
inputs relevant to the computation.

## Cache namespaces

Use logical namespaces for planner, writer, humanisation, continuity,
editorial, safety, distribution, images, embeddings, API, metadata and
locks.

## Cache candidates

-   Planner: deterministic topic classification, similarity and reusable
    planning computations.
-   Writer: identical successful generation inputs.
-   Humanisation: identical source story and editing instructions.
-   Continuity: version-bound series context and validated continuity
    outputs.
-   Editorial: reviews for identical story versions and criteria.
-   Safety: reviews for identical content and safety-policy versions.
-   Image generation: matching validated generated assets and metadata.
-   Distribution: identical approved story-version and platform inputs.
-   Analytics: short-lived caching for derived calculations.

## Never cache as reusable success

-   Human approvals.
-   Publishing actions.
-   Authentication state.
-   Unvalidated outputs.
-   Failed LLM calls as successful outputs.
-   Stale reviews.
-   Stale safety decisions.
-   Stale publishing eligibility.

## Cache invalidation

When a story is edited:

1.  Create a new immutable revision.
2.  Increment the story version.
3.  Calculate a new content hash.
4.  Invalidate dependent cache entries.
5.  Regenerate affected outputs.
6.  Rerun applicable reviews.
7.  Require new human approval.

Never reuse an approval from an older story version. Never reuse
editorial or safety approval after a relevant content or policy change.

## Concurrent requests

Implement per-key single-flight protection:

1.  Check cache.
2.  If miss, acquire a per-key lock.
3.  Recheck cache.
4.  Execute the expensive operation once.
5.  Validate result.
6.  Store validated result.
7.  Release lock.

Handle lock timeout, process cancellation, abandoned locks, stale locks
and Windows filesystem behaviour.

Do not claim filesystem locking provides distributed locking across
independent machines.

## Cache failure behaviour

Cache must fail open.

If cache reads, writes or cleanup fail: - Continue content generation. -
Do not corrupt workflow state. - Do not convert cache errors into agent
success. - Log the operational error. - Recompute when appropriate.

Corrupt cache entries must be rejected and recomputed. Only cache
validated successful results.

## TTL and cleanup

Implement default TTL, agent-specific TTL, maximum cache size, cleanup
schedule, expired-entry removal, corrupt-entry handling and retention
policies.

Never delete referenced or published assets through cache cleanup.

## Environment variables

``` env
CACHE_ENABLED=true
CACHE_BACKEND=filesystem
CACHE_DIRECTORY=./data/cache
CACHE_DEFAULT_TTL_SECONDS=3600
CACHE_LLM_TTL_SECONDS=604800
CACHE_IMAGE_TTL_SECONDS=2592000
CACHE_API_TTL_SECONDS=300
CACHE_MAX_SIZE_MB=1024
CACHE_CLEANUP_INTERVAL_HOURS=24
CACHE_LOCK_TIMEOUT_SECONDS=120
CACHE_LOCK_STALE_SECONDS=300
CACHE_FAIL_OPEN=true
```

Validate configuration during startup.

------------------------------------------------------------------------

# 10. Content Storage and File Organisation

All generated assets must be saved in the correct story-specific
directory.

Preserve existing storage conventions and migrate only when necessary.

Suggested structure:

``` text
data/
    content/
        stories/
            STORY-0001/
                metadata.json
                synopsis.md

                revisions/
                    v001/
                        original.md
                        humanised.md
                        final.md
                        reviews.json

                    v002/
                        original.md
                        humanised.md
                        final.md
                        reviews.json

                images/
                    cover.png
                    article.png
                    thumbnails/

                videos/
                    youtube_short.mp4
                    instagram_reel.mp4

                distribution/
                    substack.json
                    youtube.json
                    instagram.json
                    reddit.json

    cache/
    exports/
    backups/
    substack_automation.db
```

Implement a central content path manager.

Requirements: - Stable story IDs. - Immutable revisions. - Atomic file
writes. - Safe path construction. - Path traversal prevention. -
Extension validation. - File existence validation. - Asset metadata. -
Story-version references. - No accidental overwriting. - No deletion of
referenced or published assets.

Preserve existing asset paths when practical.

------------------------------------------------------------------------

# 11. Database and Persistence

Use existing SQLite + SQLAlchemy unless a migration is justified. Use
Alembic for schema changes. Preserve existing business records.

Existing or equivalent business entities include: - `content_calendar` -
`stories` - `story_revisions` - `story_series` - `series_continuity` -
`images` - `distribution_content` - `publishing_queue` -
`publishing_history` - `scheduled_tasks` - `platform_accounts` -
`analytics` - `content_approvals` - `content_safety_reviews` -
`editorial_reviews` - `humanisation_reviews` - `topic_history` -
`settings`

Adapt these to the existing schema. Additional business tables are
permitted where necessary.

## Strict logging rule

Do not create: - `agent_execution_logs` - `application_logs`

Do not store agent execution traces or application logs in SQLite.

Use: - LangSmith for AI traces. - Rotating files for application and
operational logs. - Filesystem cache for reusable outputs. - LangGraph
checkpointer for workflow recovery. - SQLite for business data.

Do not store raw secrets in the database or logs.

------------------------------------------------------------------------

# 12. LangSmith Observability

Integrate LangSmith for AI observability.

Capture: - Workflow execution. - Graph nodes. - Nested agent runs. -
Model calls. - Token usage. - Latency. - Tool calls. - Retries. -
Errors. - Cache hit/miss. - Context utilisation. - Prompt version. -
Model ID.

Useful metadata: - Workflow ID. - Thread ID. - Story ID. - Story
version. - Story profile. - Agent ID. - Node name. - Model identifier. -
Prompt version. - Cache status. - Input token count. - Output token
count. - Context budget.

Do not include secrets or entire story content in metadata.

Use appropriate tracing configuration. LangSmith outages must not fail
content generation.

Do not create duplicate execution logging systems in SQLite.

------------------------------------------------------------------------

# 13. React Frontend Migration

Replace the existing Streamlit frontend with React.

## Selected frontend stack

  Component       Technology
  --------------- -----------------------------------------
  Framework       React.js 18+
  Language        TypeScript
  Build tool      Vite
  Styling         Tailwind CSS
  UI library      shadcn/ui
  Icons           Lucide React
  Routing         React Router
  Server state    TanStack Query
  Client state    Zustand
  Forms           React Hook Form
  Validation      Zod
  HTTP            Axios
  Charts          Recharts
  Calendar        FullCalendar or suitable React calendar
  Notifications   Sonner

Use compatible stable versions. Inspect existing dependencies first.

## Migration rules

1.  Inspect every existing Streamlit page.
2.  Document its functionality.
3.  Map each page to a React equivalent.
4.  Reuse existing FastAPI endpoints where possible.
5.  Add endpoints only when necessary.
6.  Preserve backend business logic.
7.  Implement React incrementally.
8.  Verify the React implementation.
9.  Retire Streamlit only after successful verification.

Do not migrate business logic to React.

## Recommended frontend structure

``` text
frontend/
    public/
        assets/

    src/
        app/
            App.tsx
            router.tsx
            providers.tsx
            query-client.ts

        components/
            ui/
            layout/
            dashboard/
            calendar/
            stories/
            agents/
            approvals/
            publishing/
            analytics/
            common/

        features/
            dashboard/
            content-calendar/
            content-studio/
            story-revisions/
            humanisation/
            continuity/
            editorial-review/
            safety-review/
            image-generation/
            distribution/
            approval-centre/
            publishing-monitor/
            agent-monitor/
            analytics/
            activity-logs/
            settings/

        hooks/
        services/
        stores/
        schemas/
        types/
        utils/
        constants/
        styles/
            globals.css

        main.tsx

    tests/
    package.json
    vite.config.ts
    tsconfig.json
    tailwind.config.ts
    postcss.config.js
    index.html
```

Adapt to the repository. Do not create empty files or unnecessary
abstractions.

## Design direction

Build a premium, cinematic dark dashboard.

Brand: The Midnight Files.

Visual style: - Charcoal and near-black backgrounds. - Restrained
crimson accent. - Muted grey and off-white. - Elegant modern
typography. - Subtle borders. - Clean data tables. - Readable cards. -
Professional charts. - Consistent buttons. - Lightweight animations.

Avoid excessive red, clutter, distracting animations and generic
admin-template styling.

Support desktop, tablet and mobile. Implement accessible keyboard
navigation and clear loading, empty and error states.

## Required pages

### 1. Executive Dashboard

Display actual backend data: - Total stories. - Generated stories. -
Awaiting review. - Awaiting approval. - Approved stories. - Scheduled
publications. - Published stories. - Failed publishing tasks. - Upcoming
content. - Recent workflow activity. - Agent execution status. - Cache
hit/miss statistics. - Context-budget utilisation. - LangSmith token
usage.

Never use hardcoded dashboard metrics.

### 2. Content Calendar

-   60-day editorial calendar.
-   Monthly and weekly views.
-   Story title.
-   Genre.
-   Publishing date.
-   Platform.
-   Workflow status.
-   Filtering.
-   Rescheduling.
-   Story details.

### 3. Content Studio

-   Story creation and generation.
-   Story-type selection.
-   Dynamic word-count profile.
-   Requested and actual word count.
-   Story editor.
-   Revision history.
-   Humanisation.
-   Continuity review.
-   Editorial review.
-   Safety review.
-   Synopsis.
-   Series details.
-   Image assets.
-   Distribution previews.

Support autosave where safe. Every edit must use backend versioning and
invalidate affected reviews and approvals.

### 4. Approval Centre

Display story ID and version, editorial review, continuity review,
safety review, outstanding findings, review history and explicit
approve/reject/request-changes actions.

Approval eligibility must always be enforced by FastAPI.

### 5. Safety Review Centre

Display safety status, findings, severity, relevant passages,
recommended corrections, human-review requirements and review history.

Blocked stories must remain blocked.

### 6. Publishing Monitor

Display publishing queue, platform, story version, scheduled date,
publishing status, retry count, errors, published URL, verification
status and screenshot reference.

Allow authorised scheduling, cancellation and retry operations through
FastAPI.

### 7. Distribution Plan

Separate tabs for Substack, YouTube Shorts, Instagram Reels and Reddit.
Allow preview and editing of platform-specific content.

### 8. Agent Monitor

Display LangGraph workflow status, current agent, current workflow
stage, execution history, LangSmith trace references, model ID, token
usage, latency, cache statistics, context utilisation, errors and
retries.

Use actual backend data.

### 9. Analytics

Display actual views, reads, engagement, subscribers, watch time,
completion rate, platform comparisons, story performance and historical
trends.

Do not fabricate unavailable metrics.

### 10. Activity Logs

Read operational logs through secure FastAPI endpoints. Never expose
unrestricted filesystem access.

### 11. Settings

Include model configuration, story-length profiles, context budgets,
cache settings, LangSmith settings, scheduler settings, platform
settings, publishing configuration, retry policies and logging
configuration.

Never return raw secrets to the frontend.

## Frontend API and state management

Use TanStack Query for server state, Zustand for lightweight client-side
state, React Hook Form and Zod, and a central Axios API client.

Configure: - API base URL. - Request timeout. - Centralised error
handling. - Authentication handling if authentication exists. -
Pagination. - Filtering. - Query invalidation. - Response validation
where appropriate.

Use FastAPI OpenAPI as the API contract source of truth. Generate
TypeScript API types where practical.

Do not duplicate backend business rules.

## Workflow progress

Use a suitable backend-supported mechanism: - Server-Sent Events
(SSE). - WebSockets. - Controlled polling.

Choose the simplest reliable implementation.

Display actual LangGraph progress, for example:

``` text
Content Planner       Completed
Horror Writer         Completed
Humanisation Editor   Running
Continuity Reviewer   Pending
Editorial Reviewer    Pending
Safety Reviewer       Pending
Image Generation      Pending
Distribution          Pending
Human Approval        Pending
```

Do not simulate progress.

------------------------------------------------------------------------

# 14. FastAPI Backend

Preserve FastAPI as the only business-logic layer.

Use existing APIs where possible. Implement or extend versioned
endpoints for: - Dashboard. - Calendar. - Stories. - Story revisions. -
Series. - Agents. - Workflows. - Reviews. - Safety. - Images. -
Distribution. - Approvals. - Publishing. - Analytics. - Settings. -
Activity logs.

Use: - Pydantic request and response models. - Input validation. -
Consistent error responses. - Pagination. - Filtering. - API
versioning. - CORS configuration. - Secure settings endpoints. -
Workflow progress endpoints. - Appropriate authentication and
authorisation if present.

Preserve existing `/api/v1` routes. Do not expose database credentials,
model API keys, LangSmith keys or browser profiles.

------------------------------------------------------------------------

# 15. Playwright Publishing Automation

Implement or preserve actual authorised browser publishing.

Active publishing platforms: 1. Substack. 2. YouTube Shorts. 3.
Instagram Reels. 4. Reddit.

Podcast and audio publishing are out of scope unless explicitly
requested later.

Suggested structure:

``` text
backend/publishers/
    base_publisher.py
    substack_publisher.py
    youtube_publisher.py
    instagram_publisher.py
    reddit_publisher.py

backend/automation/
    publishing_worker.py
    browser_manager.py
    publishing_validator.py
    publishing_verifier.py
    publishing_queue.py
```

Adapt to existing code.

## Publishing worker process

Before publishing: 1. Claim a queue job safely. 2. Validate story ID. 3.
Validate exact story version. 4. Validate editorial status. 5. Validate
continuity status where applicable. 6. Validate safety status. 7.
Validate exact-version human approval. 8. Validate assets. 9. Validate
platform payload. 10. Validate schedule. 11. Check idempotency. 12.
Verify authorised browser session.

Then: 1. Open the appropriate platform. 2. Fill required content fields.
3. Upload media. 4. Configure publishing options. 5. Validate all fields
before submission. 6. Submit. 7. Verify actual publication or scheduled
status. 8. Capture the resulting URL. 9. Capture a screenshot reference
where appropriate. 10. Update publishing history.

Mark success only after verification.

## Platform-specific requirements

### Substack

Title, subtitle, article body, cover image, SEO metadata, tags,
free/premium settings, save draft, schedule, verify publication status
and store resulting URL.

### YouTube Shorts

Video, title, description, hashtags, thumbnail, audience settings,
visibility, schedule and publication verification.

### Instagram Reels

Video, caption, hashtags, cover, publishing settings and publication
verification.

### Reddit

Subreddit, title, content, discussion prompt, community rules and
submission verification.

## Security and reliability

-   Require manual login and MFA where applicable.
-   Store browser profiles outside source control.
-   Never store passwords in source code or logs.
-   Never bypass CAPTCHA, MFA or anti-bot protections.
-   Never bypass platform terms or access controls.
-   Stop safely if automation is blocked.
-   Provide a manual fallback.

Implement idempotency, configurable maximum retries (initially three),
exponential backoff, approval revalidation on every retry, safety
revalidation on every retry, destination verification before retrying
uncertain submissions and duplicate-post prevention.

Test publishing using mocked browser interactions. Never perform real
publishing during automated tests.

------------------------------------------------------------------------

# 16. Approval and Version Safeguards

These are mandatory security and business rules.

Every approval must bind to: - Story ID. - Exact story version. -
Editorial review ID. - Safety review ID. - Relevant review status. -
Approval timestamp. - Approving user.

A story edit must: 1. Create a new revision. 2. Increment the version.
3. Update the content hash. 4. Invalidate affected reviews. 5.
Invalidate dependent caches. 6. Invalidate previous approval for the new
version. 7. Require fresh reviews. 8. Require fresh human approval.

No API, frontend, scheduler, agent, queue worker or manual status update
may bypass these rules.

The publishing worker must independently validate every required gate
immediately before submission.

AI scores cannot override safety blocks.

------------------------------------------------------------------------

# 17. Scheduler

Use APScheduler.

Requirements: - Configurable 60-day content calendar. - Timezone:
`Asia/Kolkata`. - Configurable publishing schedules. - Workflow
triggering. - Publishing queue processing. - Cache cleanup. -
Operational maintenance tasks. - Job status tracking. - Failure
handling. - Retry handling.

APScheduler triggers jobs; LangGraph orchestrates agent workflows.

Prevent duplicate scheduling and duplicate execution.

------------------------------------------------------------------------

# 18. Logging and Error Handling

Use Python logging with rotating file handlers.

Separate: - Application logs. - Agent operational logs. - Publishing
logs. - Scheduler logs. - Error logs.

Use structured logs. Include identifiers such as workflow ID, story ID,
story version, agent name, operation, timestamp and severity.

Do not log secrets. Do not log complete story content unnecessarily.

Do not create application-log or agent-execution-log database tables.

LangSmith remains the primary AI execution observability system.

------------------------------------------------------------------------

# 19. Environment Configuration

Maintain `.env.example`.

Include appropriate configuration:

``` env
APP_ENV=development
APP_DEBUG=true
APP_TIMEZONE=Asia/Kolkata

OPENAI_API_KEY=
OPENAI_MODEL=

LANGSMITH_TRACING=true
LANGSMITH_API_KEY=
LANGSMITH_PROJECT=the-midnight-files

DATABASE_URL=sqlite:///./data/substack_automation.db

CACHE_ENABLED=true
CACHE_BACKEND=filesystem
CACHE_DIRECTORY=./data/cache
CACHE_DEFAULT_TTL_SECONDS=3600
CACHE_LLM_TTL_SECONDS=604800
CACHE_IMAGE_TTL_SECONDS=2592000
CACHE_API_TTL_SECONDS=300
CACHE_MAX_SIZE_MB=1024
CACHE_CLEANUP_INTERVAL_HOURS=24
CACHE_LOCK_TIMEOUT_SECONDS=120
CACHE_LOCK_STALE_SECONDS=300
CACHE_FAIL_OPEN=true

VITE_API_BASE_URL=http://localhost:8000/api/v1

MAX_REVISION_ATTEMPTS=3
PUBLISHING_MAX_RETRIES=3
```

Add other platform configuration variables as required.

Never place actual API keys or passwords in `.env.example`. Validate
required configuration at startup.

------------------------------------------------------------------------

# 20. Testing Strategy

Use automated testing throughout implementation.

## Backend

Use pytest, pytest-asyncio, HTTPX and appropriate mocks.

Test: - Every agent. - Pydantic schemas. - LangGraph workflows. -
Conditional routing. - Checkpointing. - Workflow recovery. - Human
approval interruption. - Story versioning. - Context budget. - Chunking
and reassembly. - Cache hit. - Cache miss. - Cache expiration. - Cache
invalidation. - Cache concurrency. - Cache failures. - Cache cleanup. -
Safety gates. - Publishing eligibility. - Idempotency. - Retry logic. -
Existing API regression.

## Frontend

Use Vitest and React Testing Library.

Test: - Components. - Pages. - API integrations. - Form validation. -
Query and mutation handling. - Error handling. - Workflow progress. -
Approval actions. - Story-version handling. - Responsive layouts.

## Publishing

Mock browser interactions. Never publish real content during tests.

## Regression requirements

Run all existing tests. Do not remove tests to make the build pass. Fix
regressions introduced by your changes.

------------------------------------------------------------------------

# 21. Implementation Phases

Implement in controlled phases. Do not attempt an uncontrolled rewrite.

## Phase 1: Repository assessment

-   Inspect project.
-   Document existing functionality.
-   Identify migration risks.
-   Create implementation plan.
-   Record baseline tests.

**Deliverable:** Architecture assessment.

## Phase 2: Shared infrastructure

-   Configuration.
-   Cache abstraction.
-   Cache service.
-   Cache key generation.
-   Cache invalidation.
-   Cache cleanup.
-   Context budget service.
-   Model capability registry.

**Deliverable:** Reusable infrastructure.

## Phase 3: LangGraph foundation

-   Graph state.
-   Graph builder.
-   Workflow registry.
-   Conditional routers.
-   Persistent checkpointing.
-   Human interruption.
-   Recovery.

**Deliverable:** Working orchestration foundation.

## Phase 4: Agent integration

-   Inspect existing agents.
-   Preserve and integrate them.
-   Add missing agent contracts.
-   Apply agent-specific context policies.
-   Add cache integration.
-   Add bounded execution and retries.
-   Add LangSmith tracing.

**Deliverable:** Integrated multi-agent architecture.

## Phase 5: Story management

-   Story profiles.
-   Story versioning.
-   Content path manager.
-   Revision storage.
-   Series bible.
-   Chunking.
-   Summary management.

**Deliverable:** Versioned content management.

## Phase 6: Complete workflows

-   Story generation.
-   Humanisation.
-   Continuity.
-   Editorial review.
-   Safety review.
-   Image generation.
-   Distribution.
-   Human approval.

**Deliverable:** End-to-end content generation and review.

## Phase 7: React frontend migration

-   Inspect Streamlit functionality.
-   Create React + TypeScript + Vite application.
-   Configure Tailwind CSS.
-   Implement responsive layout.
-   Implement dashboard.
-   Implement content calendar.
-   Implement Content Studio.
-   Implement reviews and approvals.
-   Implement publishing monitor.
-   Implement agent monitor.
-   Implement analytics.
-   Implement settings.

**Deliverable:** Functional React frontend integrated with FastAPI.

Do not retire Streamlit until the equivalent React functionality is
verified.

## Phase 8: Publishing automation

-   Platform adapters.
-   Queue worker.
-   Browser manager.
-   Validation.
-   Idempotency.
-   Verification.
-   Retry logic.

**Deliverable:** Safe authorised publishing workflow.

## Phase 9: Observability and operations

-   LangSmith.
-   File logging.
-   Cache monitoring.
-   Context monitoring.
-   Health checks.
-   Error handling.

**Deliverable:** Observable application.

## Phase 10: Testing and hardening

-   Unit tests.
-   Integration tests.
-   Regression tests.
-   Frontend build.
-   Security review.
-   Performance review.
-   Documentation.

**Deliverable:** Verified application.

## Phase 11: Streamlit retirement

Only after React migration is verified: - Remove Streamlit from the
active startup workflow. - Remove obsolete dependencies only when
safe. - Preserve historical source or migration documentation where
useful. - Update README and scripts.

**Deliverable:** React-only active frontend.

------------------------------------------------------------------------

# 22. Target Project Structure

Use this as the target architecture, not as an instruction to overwrite
the existing repository.

``` text
the-midnight-files/
│
├── backend/
│   ├── main.py
│   ├── config.py
│   ├── database.py
│   ├── models/
│   ├── schemas/
│   ├── api/
│   ├── agents/
│   │   ├── planner/
│   │   ├── writer/
│   │   ├── humanisation/
│   │   ├── continuity/
│   │   ├── editorial/
│   │   ├── safety/
│   │   ├── image/
│   │   ├── distribution/
│   │   ├── publishing/
│   │   └── analytics/
│   ├── orchestration/
│   │   ├── nodes/
│   │   ├── routers/
│   │   └── workflows/
│   ├── cache/
│   ├── services/
│   ├── publishers/
│   ├── automation/
│   └── utils/
│
├── frontend/
│   ├── public/
│   ├── src/
│   ├── tests/
│   └── package.json
│
├── data/
│   ├── content/
│   ├── cache/
│   ├── exports/
│   └── backups/
│
├── logs/
├── scripts/
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── workflows/
│   ├── cache/
│   └── publishing/
│
├── prompts/
├── .env.example
├── .gitignore
├── requirements.txt
├── README.md
├── PROJECT_PLAN.md
└── alembic.ini
```

------------------------------------------------------------------------

# 23. Performance and Production Readiness

Design for production-oriented reliability.

Consider: - Async FastAPI operations. - Efficient LLM calls. - Context
reduction. - Shared caching. - Bounded concurrency. - Rate-limit
handling. - API timeouts. - Controlled retries. - File I/O efficiency. -
Atomic content storage. - Workflow recovery. - Publishing idempotency. -
Database transaction safety. - Resource cleanup.

Do not introduce unnecessary microservices. Start with a modular
monolith unless the existing architecture already requires separate
services.

Keep services independently testable and clearly separated.

Design interfaces so future deployment can introduce Redis, PostgreSQL
and distributed workers without rewriting core business logic.

------------------------------------------------------------------------

# 24. Acceptance Criteria

The implementation is not complete until the following criteria are
verified.

## Existing functionality

-   Existing project features preserved.
-   Existing stories and revisions preserved.
-   Existing database records preserved.
-   Existing integrations preserved.
-   Existing APIs remain functional or have documented
    backward-compatible replacements.

## LangGraph

-   LangGraph is the central workflow orchestrator.
-   Agents are modular and independently testable.
-   Conditional routing works.
-   Revision loops are bounded.
-   Checkpointing works.
-   Workflow recovery works.
-   Human approval interruption and resume work.
-   Stale story versions cannot publish.

## Agent quality

-   Each agent has one responsibility.
-   Agent input/output schemas are validated.
-   Tool access is restricted.
-   Execution is bounded.
-   Reviews contain evidence.
-   Failed execution cannot become approval.

## Story and context management

-   Story profiles are configurable.
-   Requested word counts are respected.
-   Long stories are chunked safely.
-   Chunk reassembly preserves order and completeness.
-   Editorial review covers the complete story.
-   Safety review covers the complete required content.
-   Context budgets are enforced before every model call.
-   Summaries are versioned and invalidated correctly.

## Caching

-   Every suitable agent/service uses the shared cache.
-   Identical valid inputs reuse cached outputs.
-   Changed inputs produce different cache keys.
-   Story edits invalidate dependent cache entries.
-   Old reviews cannot be reused for new versions.
-   Old approvals cannot be reused for new versions.
-   Concurrent requests avoid unnecessary duplicate expensive
    operations.
-   Cache failures do not stop generation.
-   Corrupt entries are rejected.
-   TTL and cleanup work.
-   Published assets are not deleted by cache cleanup.

## Persistence and logging

-   SQLite contains business data only.
-   No agent execution logs table.
-   No application logs table.
-   LangSmith records AI execution and token usage.
-   Application logs are written to rotating files.
-   LangGraph checkpoints are persistent and separate.
-   Cache storage is separate from business persistence.

## Content storage

-   Assets are stored in the correct story folders.
-   Story revisions are immutable.
-   Existing assets remain intact.
-   File references remain valid.

## React frontend

-   React + TypeScript + Tailwind CSS implemented.
-   All existing Streamlit functionality has a verified React
    equivalent.
-   React communicates with FastAPI.
-   Business logic remains in FastAPI.
-   Required pages work.
-   Dashboard uses real data.
-   Workflow progress is accurate.
-   Cache and context statistics are real.
-   Approval safeguards remain enforced by the backend.
-   Publishing safeguards remain enforced.
-   Responsive layouts work.
-   Production build succeeds.
-   Frontend tests pass.

## Publishing

-   Only approved story versions can publish.
-   Safety and editorial gates are enforced.
-   Human approval is mandatory.
-   Idempotency works.
-   Retry handling works.
-   Actual publishing status is verified.
-   Uncertain submissions do not create duplicates.
-   Automated tests never publish real content.

## Final verification

-   Backend tests pass.
-   Frontend tests pass.
-   Frontend production build succeeds.
-   Existing regression tests pass.
-   Documentation is updated.
-   Windows startup scripts work.

------------------------------------------------------------------------

# 25. Final Implementation Report

After completing the work, produce a detailed implementation report.

Include:

1.  Existing architecture discovered.
2.  Existing functionality preserved.
3.  Files created.
4.  Files modified.
5.  Files left untouched.
6.  Database changes and migrations.
7.  LangGraph workflows.
8.  Graph nodes and conditional routing.
9.  Agentic principles and tool restrictions.
10. Checkpointing and recovery.
11. Story-length profiles.
12. Context-budget implementation.
13. Chunking and summary strategy.
14. Shared cache architecture.
15. Cache key and invalidation strategy.
16. Concurrency and locking implementation.
17. Cache deployment limitations.
18. Content storage changes.
19. LangSmith integration.
20. Logging architecture.
21. React frontend pages and components.
22. FastAPI endpoints reused or added.
23. Publishing worker changes.
24. Dependencies added or upgraded.
25. Backend test results.
26. Frontend test results.
27. Production build results.
28. Existing features verified.
29. Known issues and limitations.
30. Future Redis migration considerations.
31. Exact Windows startup commands.

For every feature, explicitly distinguish: - **IMPLEMENTED AND
VERIFIED** - **IMPLEMENTED BUT NOT VERIFIED** - **PARTIALLY
IMPLEMENTED** - **NOT IMPLEMENTED**

Do not claim completion merely because files were created. Provide
actual test commands and their results.

------------------------------------------------------------------------

# 26. Execution Instructions for Claude Code

Follow these instructions throughout implementation:

1.  Inspect before modifying.
2.  Create a baseline assessment.
3.  Prepare a phased implementation plan.
4.  Identify existing working implementations.
5.  Reuse existing services wherever possible.
6.  Make small, incremental changes.
7.  Test after each major phase.
8.  Preserve existing APIs and data.
9.  Avoid unnecessary dependency upgrades.
10. Do not replace working code with placeholders.
11. Do not hardcode secrets or production configuration.
12. Do not fabricate analytics or workflow status.
13. Do not weaken safety or approval gates.
14. Do not create duplicate cache, context or orchestration services.
15. Keep business logic in FastAPI.
16. Keep React focused on presentation and user interaction.
17. Use LangGraph for multi-agent orchestration.
18. Use the shared ContextBudgetService before every model call.
19. Use shared caching wherever it is beneficial and correct.
20. Keep story revisions immutable.
21. Ensure publishing is idempotent and approval-controlled.
22. Keep application logs out of SQLite.
23. Run existing regression tests.
24. Update documentation.
25. Provide the final implementation report.

If a requirement conflicts with an existing implementation, inspect the
dependency and impact before changing it. Choose the least destructive
compatible solution and document the decision.

If credentials or external access are unavailable, implement the
integration using the appropriate interface, configuration and test
mocks. Clearly identify what requires real credentials or manual
verification.

Do not stop after producing a plan. Once the assessment and
implementation plan are complete, proceed with implementation in phases,
testing continuously.

## Final objective

Deliver a maintainable, modular and production-oriented version of The
Midnight Files with:

-   React + TypeScript + Tailwind CSS frontend.
-   FastAPI backend.
-   LangGraph central orchestration.
-   LangChain-based individual agents.
-   Agent-specific context management.
-   Dynamic story-length profiles.
-   Shared intelligent caching.
-   Persistent workflow checkpointing.
-   LangSmith observability.
-   SQLite business persistence.
-   Filesystem content and cache storage.
-   Human-controlled approval.
-   Safe Playwright publishing.
-   Reliable analytics and monitoring.

Most importantly, upgrade the existing project without destroying or
unnecessarily replacing the work that has already been completed.
