import { useWorkflows } from "@/hooks/queries";
import { WorkflowInterruptPanel } from "./WorkflowInterruptPanel";

/**
 * Lists workflows for a story that expose `awaiting` interrupt data (from GET /workflows, which returns
 * WorkflowService.get() documents) and renders the revise / rerun / reject (or approve / reject) controls.
 * Renders nothing when no workflow is waiting on a human.
 */
export function AwaitingDecisions({ storyId }: { storyId: string }) {
  const q = useWorkflows();
  const waiting = (q.data?.items ?? []).filter((w) => w.story_id === storyId && w.awaiting);
  if (waiting.length === 0) return null;
  return (
    <div className="mb-4 space-y-3" aria-label="Workflows awaiting a human decision">
      {waiting.map((w) => (
        <div key={w.workflow_id}>
          <p className="mb-1 text-xs text-muted-foreground">Workflow {w.workflow_id}</p>
          <WorkflowInterruptPanel workflowId={w.workflow_id} awaiting={w.awaiting!} />
        </div>
      ))}
    </div>
  );
}
