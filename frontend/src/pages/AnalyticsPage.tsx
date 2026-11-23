import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Card, CardContent, CardHeader, CardTitle, Table, Td, Th } from "@/components/ui/primitives";
import { EmptyState, PageHeader, QueryBoundary, StatCard, StatusBadge } from "@/components/common/common";
import { useAnalyticsStories, useAnalyticsSummary } from "@/hooks/queries";
import type { AnalyticsSummary } from "@/schemas";
import { fmtNumber, humanize } from "@/lib/utils";

const tooltipStyle = { background: "#141416", border: "1px solid #2a2a2e", borderRadius: 6 };

function MetricsChart({ metrics }: { metrics: AnalyticsSummary["metrics"] }) {
  const rows = Object.entries(metrics)
    .filter(([, m]) => m.total != null)
    .map(([name, m]) => ({ name: humanize(name), total: m.total as number }));
  if (rows.length === 0) return <EmptyState title="No metric values reported" hint="Samples exist but none carry a value." />;
  return (
    <div role="img" aria-label="Metric totals chart" className="h-72">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={rows}>
          <CartesianGrid stroke="#2a2a2e" vertical={false} />
          <XAxis dataKey="name" stroke="#8a8790" />
          <YAxis stroke="#8a8790" />
          <Tooltip contentStyle={tooltipStyle} />
          <Bar dataKey="total" fill="#c0213f" radius={[3, 3, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

/** Summary is "unavailable" until metrics are captured; we show the backend message and never invent numbers. */
function Summary({ d }: { d: AnalyticsSummary }) {
  const entries = Object.entries(d.metrics);
  return (
    <div className="space-y-4">
      {d.status === "unavailable" && (
        <div role="status" className="rounded-md border border-border p-4">
          <div className="flex items-center gap-2">
            <StatusBadge status="unavailable" />
            <p className="font-medium">Analytics are unavailable</p>
          </div>
          <p className="mt-1 text-sm text-muted-foreground">{d.message ?? "No analytics metrics have been captured yet."}</p>
        </div>
      )}
      {d.publishing && (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <StatCard label="Publish attempts" value={d.publishing.attempts} />
          <StatCard label="Published" value={d.publishing.published} />
        </div>
      )}
      {entries.length > 0 && (
        <>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
            {entries.map(([k, m]) => (
              <StatCard key={k} label={humanize(k)} value={m.total == null ? "Unavailable" : fmtNumber(m.total)} hint={`${m.available_samples ?? 0} of ${m.samples ?? 0} samples available`} />
            ))}
          </div>
          <Card>
            <CardHeader>
              <CardTitle>Metric totals</CardTitle>
            </CardHeader>
            <CardContent>
              <MetricsChart metrics={d.metrics} />
            </CardContent>
          </Card>
        </>
      )}
    </div>
  );
}

export default function AnalyticsPage() {
  const summary = useAnalyticsSummary();
  const stories = useAnalyticsStories();
  return (
    <>
      <PageHeader title="Analytics" description="Metrics reported by the connected platforms. Unavailable metrics are never estimated." />
      <div className="space-y-4">
        <QueryBoundary query={summary}>{(d) => <Summary d={d} />}</QueryBoundary>
        <Card>
          <CardHeader>
            <CardTitle>Story performance</CardTitle>
          </CardHeader>
          <QueryBoundary query={stories} isEmpty={(d) => d.items.length === 0} empty={{ title: "No stories yet" }}>
            {(d) => (
              <Table>
                <thead>
                  <tr>
                    <Th>Story</Th>
                    <Th>Status</Th>
                    <Th>Metrics</Th>
                  </tr>
                </thead>
                <tbody>
                  {d.items.map((s) => (
                    <tr key={s.story_id}>
                      <Td>{s.title ?? s.story_id}</Td>
                      <Td>
                        <StatusBadge status={s.status} />
                      </Td>
                      <Td>
                        {!s.metrics ? (
                          <span className="text-muted-foreground">Unavailable</span>
                        ) : (
                          <ul className="space-y-0.5 text-xs">
                            {Object.entries(s.metrics).flatMap(([metric, byPlatform]) =>
                              Object.entries(byPlatform).map(([platform, v]) => (
                                <li key={`${metric}-${platform}`}>
                                  {humanize(metric)} · {humanize(platform)}: {v == null ? <span className="text-muted-foreground">unavailable</span> : fmtNumber(v)}
                                </li>
                              )),
                            )}
                          </ul>
                        )}
                      </Td>
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
