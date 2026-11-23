import { act, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { WorkflowProgress } from "./WorkflowProgress";
import { renderWithProviders } from "@/test/utils";
import { api } from "@/services/api";

vi.mock("@/services/api", () => ({ api: { workflow: vi.fn(), resumeWorkflow: vi.fn() } }));

const wf = (stages: { name: string; status: string }[], status = "running", extra: Record<string, unknown> = {}) => ({
  workflow_id: "WF-1", status, current_agent: "humanisation", workflow_type: "story_generation", stages, errors: [], ...extra,
});

class FakeEventSource {
  static instances: FakeEventSource[] = [];
  onopen: (() => void) | null = null;
  onmessage: (() => void) | null = null;
  onerror: (() => void) | null = null;
  listeners: Record<string, () => void> = {};
  close = vi.fn();
  constructor(public url: string) {
    FakeEventSource.instances.push(this);
  }
  addEventListener(name: string, fn: () => void) {
    this.listeners[name] = fn;
  }
}

describe("WorkflowProgress", () => {
  beforeEach(() => {
    FakeEventSource.instances = [];
  });
  afterEach(() => vi.unstubAllGlobals());

  it("renders only the stages reported by the API", async () => {
    vi.mocked(api.workflow).mockResolvedValue(wf([{ name: "planner", status: "completed" }, { name: "writer", status: "running" }]) as never);
    renderWithProviders(<WorkflowProgress workflowId="WF-1" />);
    expect(await screen.findByText("Planner")).toBeInTheDocument();
    expect(screen.getByText("Writer")).toBeInTheDocument();
    expect(screen.getByText("Completed")).toBeInTheDocument();
    expect(screen.getByText("humanisation")).toBeInTheDocument();
    expect(screen.queryByText("Safety")).not.toBeInTheDocument();
  });

  it("shows an empty state when no stages are reported", async () => {
    vi.mocked(api.workflow).mockResolvedValue(wf([], "completed") as never);
    renderWithProviders(<WorkflowProgress workflowId="WF-1" />);
    expect(await screen.findByText(/no stages reported yet/i)).toBeInTheDocument();
  });

  it("shows an error state with retry", async () => {
    vi.mocked(api.workflow).mockRejectedValue(new Error("boom"));
    renderWithProviders(<WorkflowProgress workflowId="WF-1" />);
    expect(await screen.findByRole("alert")).toHaveTextContent(/boom/);
    expect(screen.getByRole("button", { name: /try again/i })).toBeInTheDocument();
  });

  it("listens to the named SSE events and refetches the workflow document", async () => {
    vi.stubGlobal("EventSource", FakeEventSource);
    vi.mocked(api.workflow).mockResolvedValueOnce(wf([{ name: "humanise", status: "running" }]) as never);
    renderWithProviders(<WorkflowProgress workflowId="WF-1" />);
    await screen.findByText("Humanise");
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));
    const es = FakeEventSource.instances[0];
    expect(es.url).toMatch(/\/workflows\/WF-1\/events$/);
    expect(Object.keys(es.listeners)).toEqual(expect.arrayContaining(["workflow_status", "stage_started"]));
    vi.mocked(api.workflow).mockResolvedValue(wf([{ name: "humanise", status: "completed" }, { name: "continuity", status: "running" }]) as never);
    act(() => {
      es.onopen?.();
      es.listeners.stage_started();
    });
    expect(await screen.findByText("Continuity")).toBeInTheDocument();
    expect(screen.getByText(/live \(sse\)/i)).toBeInTheDocument();
  });

  it("shows human-review actions from `awaiting` and resumes with {action, notes}", async () => {
    vi.mocked(api.workflow).mockResolvedValue(
      wf([{ name: "human_review", status: "awaiting_human" }], "awaiting_human", { awaiting: { type: "human_review", story_id: "STORY-0001", version: 3, reason: "max automated revisions reached", findings: [] } }) as never,
    );
    vi.mocked(api.resumeWorkflow).mockResolvedValue({} as never);
    renderWithProviders(<WorkflowProgress workflowId="WF-1" />);
    expect(await screen.findByText("Reason: max automated revisions reached")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Rerun reviews" }));
    await waitFor(() => expect(api.resumeWorkflow).toHaveBeenCalledWith("WF-1", { action: "rerun", notes: undefined }));
  });

  it("hides decision controls when the workflow is not awaiting a human", async () => {
    vi.mocked(api.workflow).mockResolvedValue(wf([{ name: "writer", status: "running" }]) as never);
    renderWithProviders(<WorkflowProgress workflowId="WF-1" />);
    await screen.findByText("Writer");
    expect(screen.queryByRole("button", { name: "Revise" })).not.toBeInTheDocument();
  });
});
