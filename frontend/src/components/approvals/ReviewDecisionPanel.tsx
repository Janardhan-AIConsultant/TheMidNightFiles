import { useState } from "react";
import { toast } from "sonner";
import { Button, Input, Label, Textarea } from "@/components/ui/primitives";
import { useDecide } from "@/hooks/queries";
import { toApiError, type ApiError } from "@/services/client";
import type { Decision } from "@/services/api";

/**
 * Direct approval (POST /approvals): approve or reject a story version as a named human.
 * The UI never decides eligibility: every action is sent to FastAPI and any rejection
 * (missing reviews, stale version, safety block...) is shown verbatim.
 */
export function ReviewDecisionPanel({ storyId, version, onDone }: { storyId: string; version: number; onDone?: () => void }) {
  const [notes, setNotes] = useState("");
  const [approver, setApprover] = useState("operator");
  const [error, setError] = useState<ApiError | null>(null);
  const decide = useDecide();

  const submit = (decision: Decision) => {
    setError(null);
    decide.mutate(
      { story_id: storyId, version, decision, approver: approver.trim() || "operator", notes: notes.trim() || undefined },
      {
        onSuccess: () => {
          toast.success(`Decision recorded: ${decision}`);
          setNotes("");
          onDone?.();
        },
        onError: (e) => setError(toApiError(e)),
      },
    );
  };

  return (
    <div className="space-y-3">
      <div>
        <Label htmlFor="decision-approver">Approver</Label>
        <Input id="decision-approver" value={approver} onChange={(e) => setApprover(e.target.value)} />
      </div>
      <div>
        <Label htmlFor="decision-notes">Notes</Label>
        <Textarea id="decision-notes" value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Reasoning for the record" />
      </div>
      {error && (
        <div role="alert" className="rounded border border-primary/40 bg-primary/10 p-3 text-sm">
          <p className="font-medium text-primary">{error.message}</p>
          {error.reasons.length > 0 && (
            <ul className="mt-1 list-disc pl-5 text-muted-foreground">
              {error.reasons.map((r) => (
                <li key={r}>{r}</li>
              ))}
            </ul>
          )}
        </div>
      )}
      <div className="flex flex-wrap gap-2">
        <Button disabled={decide.isPending} onClick={() => submit("approve")}>
          Approve v{version}
        </Button>
        <Button variant="destructive" disabled={decide.isPending} onClick={() => submit("reject")}>
          Reject
        </Button>
      </div>
    </div>
  );
}
