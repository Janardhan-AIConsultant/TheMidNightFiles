import { useWorkflowProgress } from "@/hooks/useWorkflowProgress";
import { EmptyState, ErrorState, LoadingState, StatusBadge } from "@/components/common/common";
import { WorkflowInterruptPanel } from "./WorkflowInterruptPanel";
import { fmtNumber, humanize } from "@/lib/utils";

const errText = (e: unknown) => (typeof e === "string" ? e : ((e as { message?: string }).message ?? JSON.stringify(e)));

/** Renders only what GET /workflows/{id} (and its SSE stream) reports. Nothing is simulated. */
export function WorkflowProgress({ workflowId }: { workflowId: string }) {
  const q = useWorkflowProgress(workflowId);

  if (q.isPending) return <LoadingState label="Loading workflow" />;
  if (q.isError) return <ErrorState error={q.error} onRetry={() => void q.refetch()} />;
  const wf = q.data;
  const usage = wf.token_usage as Record<string, unknown> | undefined;
  const tokens = ["input_tokens", "output_tokens", "total_tokens"].map((k) => [k, usage?.[k]] as const).filter(([, v]) => typeof v === "number");

  return (
    <section aria-label={`Workflow ${wf.workflow_id} progress`}>
      <div className="mb-3 flex flex-wrap items-center gap-3 text-sm">
        <StatusBadge status={wf.status} />
        {wf.workflow_type && <span className="text-muted-foreground">{humanize(wf.workflow_type)}</span>}
        {wf.current_agent && (
          <span className="text-muted-foreground">
            Current agent: <span className="text-foreground">{wf.current_agent}</span>
          </span>
        )}
        {tokens.map(([k, v]) => (
          <span key={k} className="text-xs text-muted-foreground">
            {humanize(k)}: {fmtNumber(v as number)}
          </span>
        ))}
        <span className="ml-auto text-xs text-muted-foreground">{q.live ? "Live (SSE)" : q.terminal ? "Finished" : "Polling"}</span>
      </div>
      {wf.errors.length > 0 && (
        <ul role="alert" className="mb-3 space-y-1 rounded border border-primary/40 bg-primary/10 p-2 text-sm text-primary">
          {wf.errors.map((e, i) => (
            <li key={i}>{errText(e)}</li>
          ))}
        </ul>
      )}
      {wf.awaiting && (
        <div className="mb-3">
          <WorkflowInterruptPanel workflowId={wf.workflow_id} awaiting={wf.awaiting} />
        </div>
      )}
      {wf.stages.length === 0 ? (
        <EmptyState title="No stages reported yet" hint="The backend has not reported any stages for this workflow." />
      ) : (
        <ol aria-live="polite" className="divide-y divide-border rounded-md border border-border">
          {wf.stages.map((s, i) => (
            <li key={s.name} className="flex flex-wrap items-center gap-x-4 gap-y-1 px-3 py-2 text-sm">
              <span className="w-6 text-xs text-muted-foreground">{i + 1}</span>
              <span className="min-w-[10rem] flex-1 font-medium">{humanize(s.name)}</span>
              <StatusBadge status={s.status} />
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
