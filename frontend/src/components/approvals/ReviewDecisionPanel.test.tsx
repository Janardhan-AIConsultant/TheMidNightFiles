import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ReviewDecisionPanel } from "./ReviewDecisionPanel";
import { renderWithProviders } from "@/test/utils";
import { api } from "@/services/api";
import { ApiError } from "@/services/client";

vi.mock("@/services/api", () => ({ api: { decide: vi.fn() } }));

describe("ReviewDecisionPanel", () => {
  it("sends the decision to the backend without any client-side eligibility gating", async () => {
    vi.mocked(api.decide).mockResolvedValue({});
    const onDone = vi.fn();
    renderWithProviders(<ReviewDecisionPanel storyId="s1" version={3} onDone={onDone} />);
    await userEvent.type(screen.getByLabelText(/notes/i), "Looks good");
    await userEvent.click(screen.getByRole("button", { name: /approve v3/i }));
    await waitFor(() => expect(onDone).toHaveBeenCalled());
    expect(api.decide).toHaveBeenCalledWith({ story_id: "s1", version: 3, decision: "approve", approver: "operator", notes: "Looks good" });
  });

  it("displays backend eligibility errors verbatim", async () => {
    vi.mocked(api.decide).mockRejectedValue(new ApiError("approval_error", "Story is not eligible for approval", { reasons: ["Safety review not PASSED for v3"] }, 409));
    renderWithProviders(<ReviewDecisionPanel storyId="s1" version={3} />);
    await userEvent.click(screen.getByRole("button", { name: /approve v3/i }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Story is not eligible for approval");
    expect(alert).toHaveTextContent("Safety review not PASSED for v3");
    expect(screen.getByRole("button", { name: /approve v3/i })).toBeEnabled();
  });

  it("supports reject with a named approver", async () => {
    vi.mocked(api.decide).mockResolvedValue({});
    renderWithProviders(<ReviewDecisionPanel storyId="s1" version={1} />);
    await userEvent.clear(screen.getByLabelText("Approver"));
    await userEvent.type(screen.getByLabelText("Approver"), "Sam");
    await userEvent.click(screen.getByRole("button", { name: /reject/i }));
    await waitFor(() => expect(api.decide).toHaveBeenLastCalledWith(expect.objectContaining({ decision: "reject", approver: "Sam" })));
    expect(screen.queryByRole("button", { name: /request changes/i })).not.toBeInTheDocument();
  });
});
