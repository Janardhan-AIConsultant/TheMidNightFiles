import { z } from "zod";
import { request } from "./client";
import * as S from "@/schemas";

type Params = Record<string, string | number | boolean | undefined>;
const clean = (p?: Params) => (p ? Object.fromEntries(Object.entries(p).filter(([, v]) => v !== undefined && v !== "")) : undefined);

export type StoryStep = "humanise" | "continuity" | "editorial" | "safety";
/** POST /approvals accepts exactly approve | reject. */
export type Decision = "approve" | "reject";
/** Human-in-the-loop decision bodies passed to WorkflowService.resume(). */
export type ReviewAction = { action: "revise" | "rerun" | "reject"; notes?: string };
export type ApprovalDecision = { decision: "approve" | "reject"; approver: string; notes?: string };
export type ResumeDecision = ReviewAction | ApprovalDecision;

export const api = {
  dashboard: () => request(S.dashboardSchema, { url: "/dashboard/summary" }),
  cacheStats: () => request(S.cacheStatsSchema, { url: "/cache/stats" }),
  contextStats: () => request(S.contextStatsSchema, { url: "/context/stats" }),

  calendar: (params?: Params) => request(S.pageOf(S.calendarEntrySchema), { url: "/calendar", params: clean(params) }),
  createCalendarEntry: (data: { planned_date: string; topic: string; genre?: string; story_type?: string; story_id?: string }) =>
    request(S.calendarEntrySchema, { url: "/calendar", method: "POST", data }),
  rescheduleEntry: (id: string, planned_date: string) =>
    request(S.calendarEntrySchema, { url: `/calendar/${id}`, method: "PATCH", data: { planned_date } }),

  stories: (params?: Params) => request(S.pageOf(S.storySchema), { url: "/stories", params: clean(params) }),
  story: (id: string) => request(S.storySchema, { url: `/stories/${id}` }),
  createStory: (data: { title: string; genre?: string; story_type: string; target_word_count?: number; metadata?: Record<string, unknown> }) =>
    request(S.storySchema, { url: "/stories", method: "POST", data }),
  updateStory: (id: string, data: { metadata: Record<string, unknown> }) => request(S.storySchema, { url: `/stories/${id}`, method: "PATCH", data }),
  profiles: () => request(S.pageOf(S.profileSchema), { url: "/story-profiles" }),
  revisions: (id: string) => request(S.pageOf(S.revisionSchema), { url: `/stories/${id}/revisions`, params: { include_text: true, page_size: 200 } }),
  addRevision: (id: string, data: { text: string; kind: string; author: string }) =>
    request(S.revisionSchema, { url: `/stories/${id}/revisions`, method: "POST", data }),
  startStoryStep: (id: string, step: StoryStep) => request(S.workflowStartSchema, { url: `/stories/${id}/${step}`, method: "POST", data: {} }),
  startWorkflow: (data: { workflow_type: string; story_id?: string; params?: Record<string, unknown> }) =>
    request(S.workflowStartSchema, { url: "/workflows", method: "POST", data }),

  reviews: (story_id: string) => request(S.pageOf(S.reviewSchema), { url: "/reviews", params: { story_id, page_size: 200 } }),
  safetyReviews: (params?: Params) => request(S.pageOf(S.reviewSchema), { url: "/safety/reviews", params: clean(params) }),
  pendingApprovals: () => request(S.pageOf(S.pendingApprovalSchema), { url: "/approvals/pending", params: { page_size: 200 } }),
  decide: (data: { story_id: string; version: number; decision: Decision; approver: string; notes?: string }) =>
    request(S.anyObject, { url: "/approvals", method: "POST", data }),

  queue: (params?: Params) => request(S.pageOf(S.queueItemSchema), { url: "/publishing/queue", params: clean(params) }),
  enqueue: (data: { story_id: string; version: number; platform: string; scheduled_for?: string }) =>
    request(S.queueItemSchema, { url: "/publishing/queue", method: "POST", data }),
  queueAction: (id: string, action: "cancel" | "retry") =>
    request(S.queueItemSchema, { url: `/publishing/queue/${id}/${action}`, method: "POST" }),

  distribution: (storyId: string, platform: string) => request(S.distributionSchema, { url: `/distribution/${storyId}/${platform}` }),
  saveDistribution: (storyId: string, platform: string, data: { payload: Record<string, unknown>; version?: number }) =>
    request(S.distributionSchema, { url: `/distribution/${storyId}/${platform}`, method: "PUT", data }),

  workflows: () => request(S.pageOf(S.workflowSchema), { url: "/workflows", params: { page_size: 100 } }),
  workflow: (id: string) => request(S.workflowSchema, { url: `/workflows/${id}` }),
  /** The human decision is the request body; WorkflowService.resume(workflow_id, decision) consumes it. */
  resumeWorkflow: (id: string, decision: ResumeDecision) =>
    request(z.unknown(), { url: `/workflows/${id}/resume`, method: "POST", data: decision }),
  agentsStatus: () => request(S.pageOf(S.agentStatusSchema), { url: "/agents/status" }),

  analyticsSummary: () => request(S.analyticsSummarySchema, { url: "/analytics/summary" }),
  analyticsStories: () => request(S.pageOf(S.storyAnalyticsSchema), { url: "/analytics/stories", params: { page_size: 100 } }),

  logs: (params: Params) => request(S.logsSchema, { url: "/logs", params: clean(params) }),
  settings: () => request(S.settingsSchema, { url: "/settings" }),
  saveSettings: (values: Record<string, unknown>) => request(S.settingsSchema, { url: "/settings", method: "PUT", data: { values } }),
};
