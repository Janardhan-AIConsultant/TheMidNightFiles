import { z } from "zod";

/** Lenient response schemas: the FastAPI OpenAPI document is the source of truth, so we only
 *  validate the shape the UI depends on and tolerate extra/missing optional fields. */
const id = z.union([z.string(), z.number()]).transform(String);
const opt = <T extends z.ZodTypeAny>(s: T) => s.nullish();

export const pageOf = <T extends z.ZodTypeAny>(item: T) =>
  z.union([
    z.array(item).transform((items) => ({ items, total: items.length, page: 1, page_size: items.length })),
    z
      .object({ items: z.array(item), total: z.number().optional(), page: z.number().optional(), page_size: z.number().optional() })
      .transform((p) => ({ items: p.items, total: p.total ?? p.items.length, page: p.page ?? 1, page_size: p.page_size ?? p.items.length })),
  ]);

export const apiErrorBody = z.object({
  error: z.object({ code: z.string(), message: z.string(), details: z.unknown().optional() }),
});

export const storySchema = z
  .object({
    id,
    title: z.string(),
    genre: opt(z.string()),
    story_type: opt(z.string()),
    target_word_count: opt(z.number()),
    status: opt(z.string()),
    current_version: opt(z.number()),
    series_id: opt(id),
    episode_number: opt(z.number()),
    metadata: opt(z.record(z.unknown())),
    created_at: opt(z.string()),
    updated_at: opt(z.string()),
    current_revision: opt(z.object({ version: z.number(), word_count: opt(z.number()), text: opt(z.string()) }).passthrough()),
    review_state: opt(
      z
        .object({
          editorial_status: opt(z.string()),
          safety_status: opt(z.string()),
          approved: opt(z.boolean()),
          publishable: opt(z.boolean()),
          blockers: opt(z.array(z.string())),
        })
        .passthrough(),
    ),
  })
  .passthrough();

export const revisionSchema = z
  .object({
    version: z.number(),
    text: opt(z.string()),
    kind: opt(z.string()),
    author: opt(z.string()),
    created_at: opt(z.string()),
    content_hash: opt(z.string()),
    word_count: opt(z.number()),
  })
  .passthrough();

/** GET /story-profiles items are ProfileDef dataclasses: {name,target,min,max,structure,chapters}. */
export const profileSchema = z
  .object({ name: z.string(), target: opt(z.number()), min: opt(z.number()), max: opt(z.number()), structure: opt(z.string()), chapters: opt(z.number()) })
  .passthrough();

/** Agent findings: {severity, issue, location, category, explanation, recommendation}. */
export const findingSchema = z
  .object({
    severity: opt(z.string()),
    issue: opt(z.string()),
    message: opt(z.string()),
    location: opt(z.string()),
    category: opt(z.string()),
    explanation: opt(z.string()),
    recommendation: opt(z.string()),
  })
  .passthrough();

const list = <T extends z.ZodTypeAny>(item: T) => z.array(item).nullish().transform((v) => v ?? []);

export const reviewSchema = z
  .object({
    id,
    story_id: id,
    version: opt(z.number()),
    review_type: opt(z.string()),
    status: z.string(),
    findings: list(findingSchema),
    coverage: opt(z.number()),
    reviewer: opt(z.string()),
    is_valid: opt(z.boolean()),
    invalidated_reason: opt(z.string()),
    created_at: opt(z.string()),
  })
  .passthrough();

export const pendingApprovalSchema = z
  .object({
    story_id: id,
    title: opt(z.string()),
    version: z.number(),
    story_status: opt(z.string()),
    editorial_status: opt(z.string()),
    safety_status: opt(z.string()),
    safety_coverage: opt(z.number()),
  })
  .passthrough();

export const stageSchema = z.object({ name: z.string(), status: z.string() }).passthrough();

/** Interrupt payload exposed as `awaiting` by WorkflowService.get(). */
export const awaitingSchema = z
  .object({
    type: z.string(),
    story_id: opt(id),
    version: opt(z.number()),
    content_hash: opt(z.string()),
    reason: opt(z.string()),
    findings: list(findingSchema),
  })
  .passthrough();

export const workflowErrorSchema = z
  .object({ kind: opt(z.string()), message: opt(z.string()), agent_id: opt(z.string()), retryable: opt(z.boolean()) })
  .passthrough();

/** WorkflowService.get() output. */
export const workflowSchema = z
  .object({
    workflow_id: id,
    thread_id: opt(z.string()),
    story_id: opt(id),
    version: opt(z.number()),
    workflow_type: opt(z.string()),
    status: z.string(),
    current_agent: opt(z.string()),
    stages: list(stageSchema),
    token_usage: opt(z.record(z.unknown())),
    errors: list(z.union([workflowErrorSchema, z.string()])),
    retries: opt(z.number()),
    awaiting: opt(awaitingSchema),
    editorial_status: opt(z.string()),
    safety_status: opt(z.string()),
    continuity_status: opt(z.string()),
    revision_attempts: opt(z.number()),
    approval_status: opt(z.string()),
    publishing_status: opt(z.string()),
    created_at: opt(z.string()),
    updated_at: opt(z.string()),
  })
  .passthrough();

/** POST /workflows returns the workflow id (a bare string) or an object carrying it. */
export const workflowStartSchema = z
  .union([z.string(), z.object({ workflow_id: id.optional(), id: id.optional() }).passthrough()])
  .transform((v, ctx) => {
    const wid = typeof v === "string" ? v : (v.workflow_id ?? v.id);
    if (!wid) {
      ctx.addIssue({ code: "custom", message: "no workflow id in response" });
      return z.NEVER;
    }
    return { workflow_id: wid };
  });

export const calendarEntrySchema = z
  .object({ id, planned_date: z.string(), topic: z.string(), genre: opt(z.string()), story_type: opt(z.string()), story_id: opt(id), status: opt(z.string()), details: opt(z.record(z.unknown())) })
  .passthrough();
const historyItem = z
  .object({ id: opt(id), story_id: opt(id), version: opt(z.number()), platform: opt(z.string()), outcome: z.string(), external_url: opt(z.string()), published_at: opt(z.string()) })
  .passthrough();
const countMap = z.record(z.number()).nullish().transform((v) => v ?? {});

export const cacheStatsSchema = z
  .object({ hits: z.number(), misses: z.number(), errors: opt(z.number()), size_mb: opt(z.number()), enabled: opt(z.boolean()) })
  .passthrough();

const agentCtx = z.object({ calls: opt(z.number()), overflows: opt(z.number()), max_utilisation: opt(z.number()), avg_utilisation: opt(z.number()) }).passthrough();
export const contextStatsSchema = z
  .object({ agents: z.record(agentCtx).nullish().transform((v) => v ?? {}), total_calls: opt(z.number()), total_overflows: opt(z.number()) })
  .passthrough();

export const schedulerSchema = z
  .object({
    running: opt(z.boolean()),
    timezone: opt(z.string()),
    jobs: list(z.object({ id: z.string(), scheduled: opt(z.boolean()), next_run_time: opt(z.string()) }).passthrough()),
  })
  .passthrough();

/** GET /dashboard/summary */
export const dashboardSchema = z
  .object({
    generated_at: opt(z.string()),
    stories: z
      .object({
        total: z.number().default(0),
        by_status: countMap,
        recent: list(z.object({ id, title: z.string(), status: opt(z.string()), current_version: opt(z.number()), updated_at: opt(z.string()) }).passthrough()),
      })
      .passthrough(),
    approvals: z.object({ awaiting_approval: z.number().default(0) }).passthrough(),
    publishing: z.object({ queue_by_status: countMap, recent_history: list(historyItem) }).passthrough(),
    calendar: z.object({ planned_total: z.number().default(0), upcoming: list(calendarEntrySchema) }).passthrough(),
    cache: opt(cacheStatsSchema),
    context: opt(contextStatsSchema),
    scheduler: opt(schedulerSchema),
  })
  .passthrough();

/** WorkflowService.agent_status() rows. */
export const agentStatusSchema = z
  .object({
    agent_id: z.string(),
    status: z.string(),
    uses_llm: opt(z.boolean()),
    model_id: opt(z.string()),
    prompt_version: opt(z.union([z.string(), z.number()]).transform(String)),
    runs: opt(z.number()),
    failures: opt(z.number()),
    last_run: opt(z.string()),
    input_tokens: opt(z.number()),
    output_tokens: opt(z.number()),
    context_utilisation: opt(z.number()),
  })
  .passthrough();

export const QUEUE_STATUSES = ["PENDING", "CLAIMED", "PUBLISHED", "SCHEDULED", "BLOCKED", "BLOCKED_AUTOMATION", "FAILED", "UNCERTAIN", "CANCELLED"] as const;
/** Mirrors backend RETRYABLE_STATES / cancel() guards purely to disable obviously-impossible buttons; the backend still decides. */
export const RETRYABLE = ["FAILED", "BLOCKED", "BLOCKED_AUTOMATION", "UNCERTAIN", "CLAIMED"];
export const NOT_CANCELLABLE = ["PUBLISHED", "SCHEDULED", "CLAIMED", "CANCELLED"];

/** PublishingQueueService._to_dict() */
export const queueItemSchema = z
  .object({
    id,
    story_id: id,
    version: opt(z.number()),
    platform: z.string(),
    status: z.string(),
    scheduled_at: opt(z.string()),
    attempts: opt(z.number()),
    last_error: opt(z.string()),
    approval_id: opt(z.number()),
    created_at: opt(z.string()),
    idempotency_key: opt(z.string()),
    external_url: opt(z.string()),
    screenshot_ref: opt(z.string()),
    manual_fallback: opt(z.unknown()),
  })
  .passthrough();

/** DistributionContent row: the platform payload is free-form JSON produced by the distribution agent. */
export const distributionSchema = z
  .object({ story_id: opt(id), version: opt(z.number()), platform: opt(z.string()), status: opt(z.string()), payload: z.record(z.unknown()).nullish().transform((v) => v ?? {}) })
  .passthrough();

const metricTotal = z.object({ total: z.number().nullable(), samples: opt(z.number()), available_samples: opt(z.number()) }).passthrough();
export const analyticsSummarySchema = z
  .object({
    status: z.string(),
    message: opt(z.string()),
    metrics: z.record(metricTotal).nullish().transform((v) => v ?? {}),
    publishing: z.object({ attempts: z.number().default(0), published: z.number().default(0) }).passthrough().nullish(),
  })
  .passthrough();

export const storyAnalyticsSchema = z
  .object({
    story_id: id,
    title: opt(z.string()),
    status: opt(z.string()),
    status_detail: opt(z.string()),
    metrics: z.record(z.record(z.number().nullable())).nullish(),
  })
  .passthrough();

export const logEntrySchema = z
  .object({ timestamp: opt(z.string()), severity: opt(z.string()), logger: opt(z.string()), message: opt(z.string()) })
  .passthrough();
export const logsSchema = z.object({ channel: opt(z.string()), level: opt(z.string()), items: z.array(logEntrySchema), total: opt(z.number()) }).passthrough();

const secretInfo = z.object({ configured: z.boolean(), value: opt(z.string()) }).passthrough();
export const settingsSchema = z
  .object({
    config: z.object({ secrets: z.record(secretInfo).nullish() }).passthrough(),
    operator: z.record(z.unknown()).nullish().transform((v) => v ?? {}),
    editable_keys: list(z.string()),
    read_only_note: opt(z.string()),
  })
  .passthrough();
export const anyObject = z.object({}).passthrough();

export type Story = z.infer<typeof storySchema>;
export type Revision = z.infer<typeof revisionSchema>;
export type Profile = z.infer<typeof profileSchema>;
export type Review = z.infer<typeof reviewSchema>;
export type Finding = z.infer<typeof findingSchema>;
export type PendingApproval = z.infer<typeof pendingApprovalSchema>;
export type Workflow = z.infer<typeof workflowSchema>;
export type Awaiting = z.infer<typeof awaitingSchema>;
export type Dashboard = z.infer<typeof dashboardSchema>;
export type AgentStatus = z.infer<typeof agentStatusSchema>;
export type CacheStats = z.infer<typeof cacheStatsSchema>;
export type ContextStats = z.infer<typeof contextStatsSchema>;
export type CalendarEntry = z.infer<typeof calendarEntrySchema>;
export type QueueItem = z.infer<typeof queueItemSchema>;
export type Distribution = z.infer<typeof distributionSchema>;
export type AnalyticsSummary = z.infer<typeof analyticsSummarySchema>;
export type StoryAnalytics = z.infer<typeof storyAnalyticsSchema>;
export type LogEntry = z.infer<typeof logEntrySchema>;
export type Settings = z.infer<typeof settingsSchema>;

/** Highest per-agent peak context utilisation, or null when no agent has run. */
export const peakUtilisation = (c: ContextStats): number | null => {
  const v = Object.values(c.agents).map((a) => a.max_utilisation).filter((n): n is number => typeof n === "number");
  return v.length ? Math.max(...v) : null;
};

/** Platforms accepted by GET/PUT /distribution (agent PLATFORMS). */
export const PLATFORMS = [
  { id: "substack", label: "Substack" },
  { id: "youtube_shorts", label: "YouTube Shorts" },
  { id: "instagram_reels", label: "Instagram Reels" },
  { id: "reddit", label: "Reddit" },
] as const;

/** Platforms accepted by POST /publishing/queue (publishing validator PLATFORMS). */
export const PUBLISH_PLATFORMS = [
  { id: "substack", label: "Substack" },
  { id: "youtube", label: "YouTube" },
  { id: "instagram", label: "Instagram" },
  { id: "reddit", label: "Reddit" },
] as const;
