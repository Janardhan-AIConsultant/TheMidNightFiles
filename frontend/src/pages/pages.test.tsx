import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithProviders } from "@/test/utils";
import { api } from "@/services/api";
import { ApiError } from "@/services/client";
import DashboardPage from "./DashboardPage";
import PublishingMonitorPage from "./PublishingMonitorPage";
import ApprovalCentrePage from "./ApprovalCentrePage";
import AnalyticsPage from "./AnalyticsPage";
import SettingsPage, { buildValues } from "./SettingsPage";
import { CreateEntryForm } from "./CalendarPage";
import { CreateStoryForm } from "@/components/stories/CreateStoryForm";

vi.mock("@/services/api", () => ({
  api: {
    dashboard: vi.fn(), agentsStatus: vi.fn(),
    queue: vi.fn(), queueAction: vi.fn(), enqueue: vi.fn(),
    pendingApprovals: vi.fn(), reviews: vi.fn(), decide: vi.fn(), workflows: vi.fn(), resumeWorkflow: vi.fn(),
    settings: vi.fn(), saveSettings: vi.fn(),
    profiles: vi.fn(), createStory: vi.fn(), startWorkflow: vi.fn(),
    createCalendarEntry: vi.fn(), analyticsSummary: vi.fn(), analyticsStories: vi.fn(),
  },
}));

const page = <T,>(items: T[]) => ({ items, total: items.length, page: 1, page_size: items.length });

beforeEach(() => vi.clearAllMocks());

const dash = (over: Record<string, unknown> = {}) => ({
  generated_at: "2026-01-01T00:00:00",
  stories: { total: 42, by_status: { DRAFT: 40, APPROVED: 2 }, recent: [{ id: "STORY-0001", title: "Night Shift", status: "DRAFT", current_version: 1 }] },
  approvals: { awaiting_approval: 3 },
  publishing: { queue_by_status: { PENDING: 2, FAILED: 1 }, recent_history: [{ story_id: "STORY-0001", platform: "substack", outcome: "PUBLISHED" }] },
  calendar: { planned_total: 7, upcoming: [{ id: 1, topic: "The Lighthouse", planned_date: "2026-02-01T10:00:00", status: "PLANNED" }] },
  cache: { hits: 30, misses: 10, size_mb: 0 },
  context: { agents: { writer: { calls: 4, overflows: 0, max_utilisation: 0.5 } }, total_calls: 4, total_overflows: 0 },
  scheduler: { running: true, timezone: "UTC", jobs: [{ id: "calendar", scheduled: true, next_run_time: null }] },
  ...over,
});

describe("DashboardPage", () => {
  it("renders the backend summary shape", async () => {
    vi.mocked(api.dashboard).mockResolvedValue(dash() as never);
    vi.mocked(api.agentsStatus).mockResolvedValue(page([{ agent_id: "writer", status: "running" }]) as never);
    renderWithProviders(<DashboardPage />);
    expect(await screen.findByText("42")).toBeInTheDocument();
    expect(screen.getByText("The Lighthouse")).toBeInTheDocument();
    expect(screen.getByText("Night Shift")).toBeInTheDocument();
    expect(screen.getByText("75.0%")).toBeInTheDocument(); // cache hit rate
    expect(screen.getByText("50.0%")).toBeInTheDocument(); // peak context utilisation
    expect(screen.getByText("Planned in calendar").parentElement).toHaveTextContent("7");
    expect(screen.getByText("Writer")).toBeInTheDocument();
  });

  it("shows an error state when the API fails", async () => {
    vi.mocked(api.dashboard).mockRejectedValue(new ApiError("network_error", "Cannot reach the API."));
    vi.mocked(api.agentsStatus).mockRejectedValue(new Error("x"));
    renderWithProviders(<DashboardPage />);
    expect(await screen.findByText("Cannot reach the API.")).toBeInTheDocument();
  });
});

describe("PublishingMonitorPage", () => {
  const item = { id: "5", story_id: "STORY-0004", platform: "substack", status: "FAILED", attempts: 2, last_error: "Login expired", version: 4, scheduled_at: "2026-01-01T10:00:00", external_url: null };

  it("lists the queue with backend field names and triggers retry for retryable jobs", async () => {
    vi.mocked(api.queue).mockResolvedValue(page([item]) as never);
    vi.mocked(api.queueAction).mockResolvedValue(item as never);
    renderWithProviders(<PublishingMonitorPage />);
    expect(await screen.findByText("STORY-0004")).toBeInTheDocument();
    expect(screen.getByText("Login expired")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /retry job 5/i }));
    await waitFor(() => expect(api.queueAction).toHaveBeenCalledWith("5", "retry"));
  });

  it("disables retry for published jobs and cancel for jobs that cannot be cancelled", async () => {
    vi.mocked(api.queue).mockResolvedValue(page([{ ...item, id: "6", status: "PUBLISHED", last_error: null, external_url: "https://x.test/p" }]) as never);
    renderWithProviders(<PublishingMonitorPage />);
    expect(await screen.findByRole("link", { name: /published/i })).toHaveAttribute("href", "https://x.test/p");
    expect(screen.getByRole("button", { name: /retry job 6/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /cancel job 6/i })).toBeDisabled();
  });

  it("shows an empty state and validates the schedule form", async () => {
    vi.mocked(api.queue).mockResolvedValue(page([]) as never);
    renderWithProviders(<PublishingMonitorPage />);
    expect(await screen.findByText(/queue is empty/i)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Schedule" }));
    expect(await screen.findByText("Story ID is required")).toBeInTheDocument();
    expect(api.enqueue).not.toHaveBeenCalled();
  });
});

describe("ApprovalCentrePage", () => {
  const pending = { story_id: "STORY-0009", title: "Hollow Hill", version: 2, story_status: "REVIEW", editorial_status: "APPROVED", safety_status: "BLOCKED" };

  it("shows pending story, reviews and surfaces backend rejection", async () => {
    vi.mocked(api.pendingApprovals).mockResolvedValue(page([pending]) as never);
    vi.mocked(api.workflows).mockResolvedValue(page([]) as never);
    vi.mocked(api.reviews).mockResolvedValue(
      page([{ id: 1, story_id: "STORY-0009", version: 2, review_type: "safety", status: "BLOCKED", findings: [{ severity: "high", issue: "Graphic content", location: "the knife", recommendation: "Soften" }] }]) as never,
    );
    vi.mocked(api.decide).mockRejectedValue(new ApiError("approval_blocked", "Blocked by safety", { reasons: ["Safety status is BLOCKED"] }, 409));
    renderWithProviders(<ApprovalCentrePage />);
    expect(await screen.findByRole("heading", { name: /Hollow Hill.*ID STORY-0009/ })).toBeInTheDocument();
    expect(await screen.findByText("Graphic content")).toBeInTheDocument();
    expect(screen.getByText("the knife")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /approve v2/i }));
    const alert = await screen.findByText("Blocked by safety");
    expect(within(alert.closest("[role=alert]") as HTMLElement).getByText("Safety status is BLOCKED")).toBeInTheDocument();
    expect(api.decide).toHaveBeenCalledWith({ story_id: "STORY-0009", version: 2, decision: "approve", approver: "operator", notes: undefined });
  });

  it("offers revise / rerun / reject for a workflow awaiting human review and resumes with {action, notes}", async () => {
    vi.mocked(api.pendingApprovals).mockResolvedValue(page([pending]) as never);
    vi.mocked(api.reviews).mockResolvedValue(page([]) as never);
    vi.mocked(api.workflows).mockResolvedValue(
      page([
        { workflow_id: "WF-1", story_id: "STORY-0009", status: "awaiting_human", stages: [], errors: [], awaiting: { type: "human_review", story_id: "STORY-0009", version: 2, reason: "continuity=ISSUES_FOUND", findings: [{ severity: "medium", issue: "Timeline slip" }] } },
        { workflow_id: "WF-2", story_id: "OTHER", status: "awaiting_human", stages: [], errors: [], awaiting: { type: "human_review", story_id: "OTHER", version: 1 } },
      ]) as never,
    );
    vi.mocked(api.resumeWorkflow).mockResolvedValue({} as never);
    renderWithProviders(<ApprovalCentrePage />);
    expect(await screen.findByText("Human review required")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Revise" })).toHaveLength(1);
    expect(screen.getByText("Timeline slip")).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Notes", { selector: "#wf-WF-1-notes" }), "Fix timeline");
    await userEvent.click(screen.getByRole("button", { name: "Revise" }));
    await waitFor(() => expect(api.resumeWorkflow).toHaveBeenCalledWith("WF-1", { action: "revise", notes: "Fix timeline" }));
    await userEvent.click(screen.getByRole("button", { name: "Rerun reviews" }));
    await waitFor(() => expect(api.resumeWorkflow).toHaveBeenLastCalledWith("WF-1", { action: "rerun", notes: undefined }));
    await userEvent.click(screen.getAllByRole("button", { name: "Reject" })[0]);
    await waitFor(() => expect(api.resumeWorkflow).toHaveBeenLastCalledWith("WF-1", { action: "reject", notes: undefined }));
  });

  it("requires a named approver for a human_approval interrupt and sends {decision, approver}", async () => {
    vi.mocked(api.pendingApprovals).mockResolvedValue(page([pending]) as never);
    vi.mocked(api.reviews).mockResolvedValue(page([]) as never);
    vi.mocked(api.workflows).mockResolvedValue(
      page([{ workflow_id: "WF-3", story_id: "STORY-0009", status: "awaiting_human", stages: [], errors: [], awaiting: { type: "human_approval", story_id: "STORY-0009", version: 2 } }]) as never,
    );
    vi.mocked(api.resumeWorkflow).mockRejectedValue(new ApiError("conflict", "story is now v3", undefined, 409));
    renderWithProviders(<ApprovalCentrePage />);
    const panel = within(await screen.findByRole("region", { name: /human decision for workflow WF-3/i }));
    const approve = panel.getByRole("button", { name: "Approve v2" });
    expect(approve).toBeDisabled();
    await userEvent.type(screen.getByLabelText(/approver \(named human\)/i), "Sam");
    await userEvent.click(approve);
    await waitFor(() => expect(api.resumeWorkflow).toHaveBeenCalledWith("WF-3", { decision: "approve", approver: "Sam", notes: undefined }));
    expect(await screen.findByText("story is now v3")).toBeInTheDocument();
  });
});

describe("AnalyticsPage", () => {
  it("shows the unavailable state without inventing numbers", async () => {
    vi.mocked(api.analyticsSummary).mockResolvedValue({ status: "unavailable", message: "No analytics metrics have been captured yet.", metrics: {}, publishing: { attempts: 0, published: 0 } } as never);
    vi.mocked(api.analyticsStories).mockResolvedValue(page([{ story_id: "STORY-0001", title: "Night Shift", status: "DRAFT", metrics: null, status_detail: "unavailable" }]) as never);
    renderWithProviders(<AnalyticsPage />);
    expect(await screen.findByText("Analytics are unavailable")).toBeInTheDocument();
    expect(screen.getByText("No analytics metrics have been captured yet.")).toBeInTheDocument();
    expect(screen.getAllByText("Unavailable").length).toBeGreaterThanOrEqual(2); // badge + story metrics cell
  });

  it("renders available metrics and marks null values unavailable", async () => {
    vi.mocked(api.analyticsSummary).mockResolvedValue({ status: "available", message: null, metrics: { views: { total: 120, samples: 3, available_samples: 3 }, reads: { total: null, samples: 1, available_samples: 0 } } } as never);
    vi.mocked(api.analyticsStories).mockResolvedValue(page([]) as never);
    renderWithProviders(<AnalyticsPage />);
    expect(await screen.findByText("120")).toBeInTheDocument();
    expect(screen.getByText("Unavailable")).toBeInTheDocument();
  });
});

describe("SettingsPage", () => {
  const data = {
    config: { app_env: "dev", secrets: { openai_api_key: { configured: true, value: "********" } } },
    operator: { "scheduler.calendar_hour": 6, "scheduler.enabled": true },
    editable_keys: ["scheduler.calendar_hour", "scheduler.enabled", "ui.theme"],
    read_only_note: "Secrets come from the environment.",
  };

  it("sends only changed editable keys, coerced, wrapped as {values}", async () => {
    vi.mocked(api.settings).mockResolvedValue(data as never);
    vi.mocked(api.saveSettings).mockResolvedValue(data as never);
    renderWithProviders(<SettingsPage />);
    const hour = await screen.findByLabelText("Scheduler Calendar Hour");
    await userEvent.clear(hour);
    await userEvent.type(hour, "8");
    await userEvent.click(screen.getByRole("button", { name: /save settings/i }));
    await waitFor(() => expect(api.saveSettings).toHaveBeenCalled());
    expect(vi.mocked(api.saveSettings).mock.calls[0][0]).toEqual({ "scheduler.calendar_hour": 8 });
    expect(screen.getByText("********")).toBeInTheDocument();
  });

  it("buildValues omits unchanged and blank fields", () => {
    expect(buildValues({ "scheduler.enabled": false, "ui.theme": "", "scheduler.calendar_hour": "6" }, { "scheduler.enabled": true, "scheduler.calendar_hour": 6 })).toEqual({ "scheduler.enabled": false });
  });
});

describe("CalendarPage create form", () => {
  it("validates, then posts {planned_date, topic, ...} to the backend", async () => {
    vi.mocked(api.createCalendarEntry).mockResolvedValue({ id: 1, topic: "T", planned_date: "2026-03-01T10:00:00" } as never);
    renderWithProviders(<CreateEntryForm />);
    await userEvent.click(screen.getByRole("button", { name: /add to calendar/i }));
    expect(await screen.findByText("Topic is required")).toBeInTheDocument();
    expect(api.createCalendarEntry).not.toHaveBeenCalled();
    await userEvent.type(screen.getByLabelText("Topic"), "Haunted lighthouse");
    await userEvent.type(screen.getByLabelText("Planned date"), "2026-03-01T10:00");
    await userEvent.click(screen.getByRole("button", { name: /add to calendar/i }));
    await waitFor(() => expect(api.createCalendarEntry).toHaveBeenCalled());
    const sent = vi.mocked(api.createCalendarEntry).mock.calls[0][0];
    expect(sent.topic).toBe("Haunted lighthouse");
    expect(sent.story_type).toBe("standalone");
    expect(new Date(sent.planned_date).toISOString()).toBe(sent.planned_date);
  });
});

describe("CreateStoryForm", () => {
  beforeEach(() => {
    vi.mocked(api.profiles).mockResolvedValue(page([{ name: "Flash Fiction", target: 500, min: 400, max: 600 }]) as never);
  });

  it("validates required fields", async () => {
    renderWithProviders(<CreateStoryForm onCreated={vi.fn()} />);
    await userEvent.click(screen.getByRole("button", { name: /create story/i }));
    expect(await screen.findByText(/at least 3 characters/i)).toBeInTheDocument();
    expect(screen.getByText("Choose a story type")).toBeInTheDocument();
    expect(api.createStory).not.toHaveBeenCalled();
  });

  it("submits the backend StoryCreate payload, then starts a story_generation workflow", async () => {
    vi.mocked(api.createStory).mockResolvedValue({ id: "STORY-0005", title: "Night Shift" } as never);
    vi.mocked(api.startWorkflow).mockResolvedValue({ workflow_id: "WF-1" } as never);
    const onCreated = vi.fn();
    renderWithProviders(<CreateStoryForm onCreated={onCreated} />);
    await screen.findByRole("option", { name: "Flash Fiction" });
    await userEvent.type(screen.getByLabelText("Title"), "Night Shift");
    await userEvent.selectOptions(screen.getByLabelText("Story type"), "flash_fiction");
    expect(screen.getByText(/400–600 words, target 500/)).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Target word count"), "450");
    await userEvent.type(screen.getByLabelText(/brief/i), "A lighthouse keeper");
    await userEvent.click(screen.getByRole("button", { name: /create story/i }));
    await waitFor(() => expect(onCreated).toHaveBeenCalledWith("STORY-0005"));
    expect(vi.mocked(api.createStory).mock.calls[0][0]).toEqual({ title: "Night Shift", story_type: "flash_fiction", target_word_count: 450, genre: "horror", metadata: { brief: "A lighthouse keeper" } });
    expect(vi.mocked(api.startWorkflow).mock.calls[0][0]).toEqual({
      workflow_type: "story_generation",
      story_id: "STORY-0005",
      params: { story_type: "flash_fiction", target_word_count: 450, brief: "A lighthouse keeper" },
    });
  });
});
