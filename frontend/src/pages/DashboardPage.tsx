import { Card, CardContent, CardHeader, CardTitle, Table, Td, Th } from "@/components/ui/primitives";
import { EmptyState, ErrorState, LoadingState, PageHeader, StatCard, StatusBadge } from "@/components/common/common";
import { useAgentsStatus, useDashboard } from "@/hooks/queries";
import { QUEUE_STATUSES, peakUtilisation } from "@/schemas";
import { fmtDate, fmtNumber, humanize } from "@/lib/utils";
import { QueryBoundary } from "@/components/common/common";

const pct = (n: number | null | undefined) => (n == null ? "—" : `${(n <= 1 ? n * 100 : n).toFixed(1)}%`);

export default function DashboardPage() {
  const dash = useDashboard();
  const agents = useAgentsStatus();

  return (
    <>
      <PageHeader title="Executive Dashboard" description="Live pipeline, publishing and infrastructure status from the backend." />
      {dash.isPending ? (
        <LoadingState label="Loading dashboard" />
      ) : dash.isError ? (
        <ErrorState error={dash.error} onRetry={() => void dash.refetch()} />
      ) : (
        (() => {
          const d = dash.data;
          const queue = d.publishing.queue_by_status;
          const cache = d.cache;
          const total = cache ? cache.hits + cache.misses : 0;
          return (
            <div className="space-y-6">
              <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
                <StatCard label="Total stories" value={d.stories.total} />
                <StatCard label="Awaiting approval" value={d.approvals.awaiting_approval} />
                <StatCard label="Planned in calendar" value={d.calendar.planned_total} />
                <StatCard label="Published jobs" value={queue.PUBLISHED ?? 0} />
              </div>

              <div className="grid gap-4 lg:grid-cols-2">
                <Card>
                  <CardHeader>
                    <CardTitle>Stories by status</CardTitle>
                  </CardHeader>
                  {Object.keys(d.stories.by_status).length === 0 ? (
                    <EmptyState title="No stories yet" />
                  ) : (
                    <ul className="divide-y divide-border">
                      {Object.entries(d.stories.by_status).map(([k, v]) => (
                        <li key={k} className="flex items-center justify-between px-4 py-2 text-sm">
                          <StatusBadge status={k} />
                          <span>{fmtNumber(v)}</span>
                        </li>
                      ))}
                    </ul>
                  )}
                </Card>
                <Card>
                  <CardHeader>
                    <CardTitle>Publishing queue</CardTitle>
                  </CardHeader>
                  <ul className="divide-y divide-border">
                    {[...QUEUE_STATUSES, ...Object.keys(queue).filter((k) => !(QUEUE_STATUSES as readonly string[]).includes(k))].map((k) => (
                      <li key={k} className="flex items-center justify-between px-4 py-2 text-sm">
                        <StatusBadge status={k} />
                        <span>{fmtNumber(queue[k] ?? 0)}</span>
                      </li>
                    ))}
                  </ul>
                </Card>
              </div>

              <div className="grid gap-4 lg:grid-cols-3">
                <Card>
                  <CardHeader>
                    <CardTitle>Upcoming content</CardTitle>
                  </CardHeader>
                  {d.calendar.upcoming.length === 0 ? (
                    <EmptyState title="Nothing scheduled" />
                  ) : (
                    <ul className="divide-y divide-border">
                      {d.calendar.upcoming.map((u) => (
                        <li key={u.id} className="flex justify-between gap-2 px-4 py-2 text-sm">
                          <span>{u.topic}</span>
                          <span className="text-muted-foreground">{fmtDate(u.planned_date)}</span>
                        </li>
                      ))}
                    </ul>
                  )}
                </Card>
                <Card>
                  <CardHeader>
                    <CardTitle>Recent stories</CardTitle>
                  </CardHeader>
                  {d.stories.recent.length === 0 ? (
                    <EmptyState title="No recent activity" />
                  ) : (
                    <ul className="divide-y divide-border">
                      {d.stories.recent.map((s) => (
                        <li key={s.id} className="flex items-center justify-between gap-2 px-4 py-2 text-sm">
                          <span>{s.title}</span>
                          <span className="flex shrink-0 items-center gap-2">
                            <StatusBadge status={s.status} />
                            <span className="text-xs text-muted-foreground">{fmtDate(s.updated_at)}</span>
                          </span>
                        </li>
                      ))}
                    </ul>
                  )}
                </Card>
                <Card>
                  <CardHeader>
                    <CardTitle>Recent publishing history</CardTitle>
                  </CardHeader>
                  {d.publishing.recent_history.length === 0 ? (
                    <EmptyState title="Nothing published yet" />
                  ) : (
                    <ul className="divide-y divide-border">
                      {d.publishing.recent_history.map((h, i) => (
                        <li key={h.id ?? i} className="flex items-center justify-between gap-2 px-4 py-2 text-sm">
                          <span>
                            {h.story_id} · {humanize(h.platform)}
                          </span>
                          <span className="flex shrink-0 items-center gap-2">
                            <StatusBadge status={h.outcome} />
                            <span className="text-xs text-muted-foreground">{fmtDate(h.published_at)}</span>
                          </span>
                        </li>
                      ))}
                    </ul>
                  )}
                </Card>
              </div>

              <div className="grid gap-4 md:grid-cols-3">
                <Card>
                  <CardHeader>
                    <CardTitle>Cache</CardTitle>
                  </CardHeader>
                  <CardContent>
                    {cache ? (
                      <dl className="grid grid-cols-2 gap-2 text-sm">
                        <dt className="text-muted-foreground">Hits</dt>
                        <dd>{fmtNumber(cache.hits)}</dd>
                        <dt className="text-muted-foreground">Misses</dt>
                        <dd>{fmtNumber(cache.misses)}</dd>
                        <dt className="text-muted-foreground">Hit rate</dt>
                        <dd>{total ? pct(cache.hits / total) : "—"}</dd>
                      </dl>
                    ) : (
                      <p className="text-sm text-muted-foreground">Not reported by the backend.</p>
                    )}
                  </CardContent>
                </Card>
                <Card>
                  <CardHeader>
                    <CardTitle>Context budget</CardTitle>
                  </CardHeader>
                  <CardContent>
                    {d.context ? (
                      <dl className="grid grid-cols-2 gap-2 text-sm">
                        <dt className="text-muted-foreground">Calls</dt>
                        <dd>{fmtNumber(d.context.total_calls)}</dd>
                        <dt className="text-muted-foreground">Peak utilisation</dt>
                        <dd>{pct(peakUtilisation(d.context))}</dd>
                        <dt className="text-muted-foreground">Overflows</dt>
                        <dd>{fmtNumber(d.context.total_overflows)}</dd>
                      </dl>
                    ) : (
                      <p className="text-sm text-muted-foreground">Not reported by the backend.</p>
                    )}
                  </CardContent>
                </Card>
                <Card>
                  <CardHeader>
                    <CardTitle>Scheduler</CardTitle>
                  </CardHeader>
                  <CardContent>
                    {d.scheduler ? (
                      <div className="space-y-2 text-sm">
                        <StatusBadge status={d.scheduler.running ? "running" : "stopped"} />
                        <ul className="space-y-1 text-xs text-muted-foreground">
                          {d.scheduler.jobs.map((j) => (
                            <li key={j.id}>
                              {humanize(j.id)}: {j.next_run_time ? `next ${fmtDate(j.next_run_time)}` : "not scheduled"}
                            </li>
                          ))}
                        </ul>
                      </div>
                    ) : (
                      <p className="text-sm text-muted-foreground">Scheduler is disabled.</p>
                    )}
                  </CardContent>
                </Card>
              </div>

              <Card>
                <CardHeader>
                  <CardTitle>Agent execution status</CardTitle>
                </CardHeader>
                <QueryBoundary query={agents} isEmpty={(a) => a.items.length === 0} empty={{ title: "No agent runs yet" }}>
                  {(a) => (
                    <Table>
                      <thead>
                        <tr>
                          <Th>Agent</Th>
                          <Th>Status</Th>
                          <Th>Last run</Th>
                        </tr>
                      </thead>
                      <tbody>
                        {a.items.map((x) => (
                          <tr key={x.agent_id}>
                            <Td>{humanize(x.agent_id)}</Td>
                            <Td>
                              <StatusBadge status={x.status} />
                            </Td>
                            <Td>{fmtDate(x.last_run)}</Td>
                          </tr>
                        ))}
                      </tbody>
                    </Table>
                  )}
                </QueryBoundary>
              </Card>
            </div>
          );
        })()
      )}
    </>
  );
}
