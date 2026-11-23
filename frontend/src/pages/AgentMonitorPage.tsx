import { useState } from "react";
import { Card, CardContent, CardHeader, CardTitle, Table, Td, Th } from "@/components/ui/primitives";
import { PageHeader, QueryBoundary, StatusBadge } from "@/components/common/common";
import { WorkflowProgress } from "@/components/workflow/WorkflowProgress";
import { useAgentsStatus, useCacheStats, useContextStats, useWorkflows } from "@/hooks/queries";
import { peakUtilisation } from "@/schemas";
import { cn, fmtDate, fmtNumber, humanize } from "@/lib/utils";

const pct = (n: number | null | undefined) => (n == null ? "—" : `${(n <= 1 ? n * 100 : n).toFixed(1)}%`);

export default function AgentMonitorPage() {
  const workflows = useWorkflows();
  const agents = useAgentsStatus();
  const cache = useCacheStats();
  const ctx = useContextStats();
  const [selected, setSelected] = useState<string>();

  return (
    <>
      <PageHeader title="Agent Monitor" description="LangGraph workflow execution, model usage and infrastructure statistics from the backend." />
      <div className="space-y-4">
        <div className="grid gap-4 lg:grid-cols-[22rem_1fr]">
          <Card className="self-start">
            <CardHeader>
              <CardTitle>Workflows</CardTitle>
            </CardHeader>
            <QueryBoundary query={workflows} isEmpty={(d) => d.items.length === 0} empty={{ title: "No workflow runs yet" }}>
              {(d) => (
                <ul className="max-h-[26rem] divide-y divide-border overflow-y-auto">
                  {d.items.map((w) => (
                    <li key={w.workflow_id}>
                      <button
                        type="button"
                        aria-pressed={(selected ?? d.items[0].workflow_id) === w.workflow_id}
                        onClick={() => setSelected(w.workflow_id)}
                        className={cn("flex w-full items-center justify-between gap-2 px-4 py-2 text-left text-sm hover:bg-muted", (selected ?? d.items[0].workflow_id) === w.workflow_id && "bg-muted")}
                      >
                        <span className="min-w-0">
                          <span className="block truncate">{humanize(w.workflow_type)} · {w.workflow_id}</span>
                          <span className="text-xs text-muted-foreground">{fmtDate(w.created_at)}</span>
                        </span>
                        <StatusBadge status={w.status} />
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </QueryBoundary>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle>Execution</CardTitle>
            </CardHeader>
            <CardContent>
              {workflows.data && workflows.data.items.length > 0 ? (
                <WorkflowProgress key={selected ?? workflows.data.items[0].workflow_id} workflowId={selected ?? workflows.data.items[0].workflow_id} />
              ) : (
                <p className="text-sm text-muted-foreground">Select a workflow to see its steps.</p>
              )}
            </CardContent>
          </Card>
        </div>

        <div className="grid gap-4 md:grid-cols-2">
          <Card>
            <CardHeader>
              <CardTitle>Cache statistics</CardTitle>
            </CardHeader>
            <CardContent>
              <QueryBoundary query={cache}>
                {(c) => (
                  <dl className="grid grid-cols-2 gap-2 text-sm">
                    <dt className="text-muted-foreground">Hits / misses</dt>
                    <dd>{fmtNumber(c.hits)} / {fmtNumber(c.misses)}</dd>
                    <dt className="text-muted-foreground">Errors</dt>
                    <dd>{fmtNumber(c.errors)}</dd>
                    <dt className="text-muted-foreground">Size (MB)</dt>
                    <dd>{c.size_mb ?? "—"}</dd>
                  </dl>
                )}
              </QueryBoundary>
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle>Context utilisation</CardTitle>
            </CardHeader>
            <CardContent>
              <QueryBoundary query={ctx}>
                {(c) => (
                  <dl className="grid grid-cols-2 gap-2 text-sm">
                    <dt className="text-muted-foreground">Calls</dt>
                    <dd>{fmtNumber(c.total_calls)}</dd>
                    <dt className="text-muted-foreground">Peak</dt>
                    <dd>{pct(peakUtilisation(c))}</dd>
                    <dt className="text-muted-foreground">Overflows</dt>
                    <dd>{fmtNumber(c.total_overflows)}</dd>
                  </dl>
                )}
              </QueryBoundary>
            </CardContent>
          </Card>
        </div>

        <Card>
          <CardHeader>
            <CardTitle>Agents</CardTitle>
          </CardHeader>
          <QueryBoundary query={agents} isEmpty={(d) => d.items.length === 0} empty={{ title: "No agent activity recorded" }}>
            {(d) => (
              <Table>
                <thead>
                  <tr>
                    <Th>Agent</Th>
                    <Th>Status</Th>
                    <Th>Model</Th>
                    <Th>Runs</Th>
                    <Th>Failures</Th>
                    <Th>Tokens in / out</Th>
                    <Th>Context</Th>
                    <Th>Last run</Th>
                  </tr>
                </thead>
                <tbody>
                  {d.items.map((a) => (
                    <tr key={a.agent_id}>
                      <Td>{humanize(a.agent_id)}</Td>
                      <Td>
                        <StatusBadge status={a.status} />
                      </Td>
                      <Td>{a.uses_llm === false ? "No LLM" : (a.model_id ?? "—")}</Td>
                      <Td>{fmtNumber(a.runs)}</Td>
                      <Td>{fmtNumber(a.failures)}</Td>
                      <Td>
                        {fmtNumber(a.input_tokens)} / {fmtNumber(a.output_tokens)}
                      </Td>
                      <Td>{pct(a.context_utilisation)}</Td>
                      <Td>{fmtDate(a.last_run)}</Td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            )}
          </QueryBoundary>
        </Card>
      </div>
    </>
  );
}
