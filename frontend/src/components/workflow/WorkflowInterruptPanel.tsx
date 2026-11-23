import { useState } from "react";
import { Button, Input, Label, Textarea } from "@/components/ui/primitives";
import { StatusBadge } from "@/components/common/common";
import { FindingList } from "@/components/approvals/ReviewList";
import { useResumeWorkflow } from "@/hooks/queries";
import { toApiError, type ApiError } from "@/services/client";
import type { Awaiting } from "@/schemas";
import type { ResumeDecision } from "@/services/api";

/**
 * Human-in-the-loop controls for a workflow whose `awaiting` interrupt payload is present.
 *  - human_review   -> resume body {action: revise | rerun | reject, notes}
 *  - human_approval -> resume body {decision: approve | reject, approver, notes}
 * Eligibility (stale version, blocked safety...) is decided by the backend and shown verbatim.
 */
export function WorkflowInterruptPanel({ workflowId, awaiting, onDone }: { workflowId: string; awaiting: Awaiting; onDone?: () => void }) {
  const [notes, setNotes] = useState("");
  const [approver, setApprover] = useState("");
  const [error, setError] = useState<ApiError | null>(null);
  const resume = useResumeWorkflow();
  const isApproval = awaiting.type === "human_approval";
  const isReview = awaiting.type === "human_review";

  const send = (decision: ResumeDecision) => {
    setError(null);
    resume.mutate(
      { id: workflowId, decision },
      {
        onSuccess: () => {
          setNotes("");
          onDone?.();
        },
        onError: (e) => setError(toApiError(e)),
      },
    );
  };
  const n = notes.trim() || undefined;
  const uid = `wf-${workflowId}`;

  return (
    <section aria-label={`Human decision for workflow ${workflowId}`} className="space-y-3 rounded-md border border-warning/40 bg-warning/5 p-3">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <StatusBadge status="awaiting_human" />
        <span className="font-medium">{isApproval ? "Human approval required" : isReview ? "Human review required" : `Waiting for human input (${awaiting.type})`}</span>
        {awaiting.story_id && (
          <span className="text-xs text-muted-foreground">
            {awaiting.story_id}
            {awaiting.version != null ? ` · v${awaiting.version}` : ""}
          </span>
        )}
      </div>
      {awaiting.reason && <p className="text-sm text-muted-foreground">Reason: {awaiting.reason}</p>}
      {(awaiting.findings?.length ?? 0) > 0 && <FindingList findings={awaiting.findings} />}
      {isApproval && (
        <div>
          <Label htmlFor={`${uid}-approver`}>Approver (named human)</Label>
          <Input id={`${uid}-approver`} value={approver} onChange={(e) => setApprover(e.target.value)} autoComplete="name" />
        </div>
      )}
      <div>
        <Label htmlFor={`${uid}-notes`}>Notes</Label>
        <Textarea id={`${uid}-notes`} value={notes} onChange={(e) => setNotes(e.target.value)} placeholder={isReview ? "Guidance for the writer when requesting a revision" : "Reasoning for the record"} />
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
        {isReview && (
          <>
            <Button disabled={resume.isPending} onClick={() => send({ action: "revise", notes: n })}>
              Revise
            </Button>
            <Button variant="secondary" disabled={resume.isPending} onClick={() => send({ action: "rerun", notes: n })}>
              Rerun reviews
            </Button>
            <Button variant="destructive" disabled={resume.isPending} onClick={() => send({ action: "reject", notes: n })}>
              Reject
            </Button>
          </>
        )}
        {isApproval && (
          <>
            <Button disabled={resume.isPending || !approver.trim()} onClick={() => send({ decision: "approve", approver: approver.trim(), notes: n })}>
              Approve v{awaiting.version}
            </Button>
            <Button variant="destructive" disabled={resume.isPending || !approver.trim()} onClick={() => send({ decision: "reject", approver: approver.trim(), notes: n })}>
              Reject
            </Button>
          </>
        )}
      </div>
    </section>
  );
}
