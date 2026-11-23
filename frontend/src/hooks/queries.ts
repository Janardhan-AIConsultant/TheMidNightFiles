import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { api, type Decision, type ResumeDecision, type StoryStep } from "@/services/api";

export const keys = {
  dashboard: ["dashboard"] as const,
  calendar: ["calendar"] as const,
  stories: ["stories"] as const,
  story: (id: string) => ["stories", id] as const,
  revisions: (id: string) => ["stories", id, "revisions"] as const,
  reviews: (id: string) => ["reviews", id] as const,
  approvals: ["approvals"] as const,
  safety: ["safety"] as const,
  queue: ["queue"] as const,
  workflows: ["workflows"] as const,
  workflow: (id: string) => ["workflows", id] as const,
};

export const useDashboard = () => useQuery({ queryKey: keys.dashboard, queryFn: api.dashboard, refetchInterval: 30_000 });
export const useCacheStats = () => useQuery({ queryKey: ["cache-stats"], queryFn: api.cacheStats, refetchInterval: 30_000 });
export const useContextStats = () => useQuery({ queryKey: ["context-stats"], queryFn: api.contextStats, refetchInterval: 30_000 });

export const useCalendar = () => useQuery({ queryKey: keys.calendar, queryFn: () => api.calendar({ page_size: 200 }) });
export function useCreateCalendarEntry() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.createCalendarEntry,
    onSuccess: () => {
      toast.success("Calendar entry created");
      return Promise.all([qc.invalidateQueries({ queryKey: keys.calendar }), qc.invalidateQueries({ queryKey: keys.dashboard })]);
    },
  });
}
export function useReschedule() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { id: string; planned_date: string }) => api.rescheduleEntry(v.id, v.planned_date),
    onSuccess: () => {
      toast.success("Publication rescheduled");
      return qc.invalidateQueries({ queryKey: keys.calendar });
    },
  });
}

export const useStories = () => useQuery({ queryKey: keys.stories, queryFn: () => api.stories({ page_size: 100 }) });
export const useStory = (id?: string) => useQuery({ queryKey: keys.story(id ?? ""), queryFn: () => api.story(id!), enabled: !!id });
export const useProfiles = () => useQuery({ queryKey: ["profiles"], queryFn: api.profiles, staleTime: 5 * 60_000 });
export const useRevisions = (id?: string) => useQuery({ queryKey: keys.revisions(id ?? ""), queryFn: () => api.revisions(id!), enabled: !!id });

export function useCreateStory() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.createStory,
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.stories }),
  });
}

/** New revisions invalidate server-side reviews and approvals, so refetch everything derived from a story. */
export function useAddRevision(storyId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { text: string; kind: string }) => api.addRevision(storyId, { ...v, author: "editor" }),
    onSuccess: () => {
      toast.success("New revision saved. Existing reviews and approvals must be re-run.");
      return Promise.all([
        qc.invalidateQueries({ queryKey: keys.story(storyId) }),
        qc.invalidateQueries({ queryKey: keys.reviews(storyId) }),
        qc.invalidateQueries({ queryKey: keys.approvals }),
        qc.invalidateQueries({ queryKey: keys.safety }),
      ]);
    },
  });
}

export function useUpdateStory(storyId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (metadata: Record<string, unknown>) => api.updateStory(storyId, { metadata }),
    onSuccess: () => {
      toast.success("Story details saved");
      return qc.invalidateQueries({ queryKey: keys.story(storyId) });
    },
  });
}

export function useStartStoryStep(storyId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (step: StoryStep) => api.startStoryStep(storyId, step),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.workflows }),
  });
}

export function useStartWorkflow() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.startWorkflow,
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.workflows }),
  });
}

/** Resume an interrupted (awaiting_human) workflow with a human decision. */
export function useResumeWorkflow() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { id: string; decision: ResumeDecision }) => api.resumeWorkflow(v.id, v.decision),
    meta: { silent: true },
    onSuccess: (_d, v) => {
      toast.success("Decision sent to the workflow");
      return Promise.all([
        qc.invalidateQueries({ queryKey: keys.workflow(v.id) }),
        qc.invalidateQueries({ queryKey: keys.workflows }),
        qc.invalidateQueries({ queryKey: keys.approvals }),
        qc.invalidateQueries({ queryKey: keys.dashboard }),
      ]);
    },
  });
}

export const useReviews = (storyId?: string) => useQuery({ queryKey: keys.reviews(storyId ?? ""), queryFn: () => api.reviews(storyId!), enabled: !!storyId });
export const useSafetyReviews = () => useQuery({ queryKey: keys.safety, queryFn: () => api.safetyReviews({ page_size: 100 }) });
export const usePendingApprovals = () => useQuery({ queryKey: keys.approvals, queryFn: api.pendingApprovals });

/** Eligibility is decided by FastAPI; failures are rethrown to the caller and toasted centrally. */
export function useDecide() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { story_id: string; version: number; decision: Decision; approver: string; notes?: string }) => api.decide(v),
    meta: { silent: true },
    onSuccess: () => Promise.all([qc.invalidateQueries({ queryKey: keys.approvals }), qc.invalidateQueries({ queryKey: keys.dashboard })]),
  });
}

export const usePublishQueue = (status = "") =>
  useQuery({ queryKey: [...keys.queue, status], queryFn: () => api.queue({ page_size: 100, status }), refetchInterval: 15_000 });
export function useQueueAction() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { id: string; action: "cancel" | "retry" }) => api.queueAction(v.id, v.action),
    onSuccess: (_d, v) => {
      toast.success(v.action === "cancel" ? "Publication cancelled" : "Retry requested");
      return qc.invalidateQueries({ queryKey: keys.queue });
    },
  });
}
export function useEnqueue() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.enqueue,
    onSuccess: () => {
      toast.success("Publication scheduled");
      return qc.invalidateQueries({ queryKey: keys.queue });
    },
  });
}

export const useDistribution = (storyId: string | undefined, platform: string) =>
  useQuery({ queryKey: ["distribution", storyId, platform], queryFn: () => api.distribution(storyId!, platform), enabled: !!storyId });
export function useSaveDistribution(storyId: string, platform: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: { payload: Record<string, unknown> }) => api.saveDistribution(storyId, platform, data),
    onSuccess: () => {
      toast.success("Distribution content saved");
      return qc.invalidateQueries({ queryKey: ["distribution", storyId, platform] });
    },
  });
}

export const useWorkflows = () => useQuery({ queryKey: keys.workflows, queryFn: api.workflows, refetchInterval: 10_000 });
export const useAgentsStatus = () => useQuery({ queryKey: ["agents-status"], queryFn: api.agentsStatus, refetchInterval: 10_000 });

export const useAnalyticsSummary = () => useQuery({ queryKey: ["analytics", "summary"], queryFn: api.analyticsSummary });
export const useAnalyticsStories = () => useQuery({ queryKey: ["analytics", "stories"], queryFn: api.analyticsStories });

export const useLogs = (p: { channel: string; level: string; limit: number }) =>
  useQuery({ queryKey: ["logs", p], queryFn: () => api.logs(p), refetchInterval: 15_000 });

export const useSettings = () => useQuery({ queryKey: ["settings"], queryFn: api.settings });
export function useSaveSettings() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (values: Record<string, unknown>) => api.saveSettings(values),
    onSuccess: (data) => {
      toast.success("Settings saved");
      qc.setQueryData(["settings"], data);
    },
  });
}
