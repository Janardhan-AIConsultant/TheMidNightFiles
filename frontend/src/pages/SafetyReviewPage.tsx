import { useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/primitives";
import { PageHeader, QueryBoundary, StatusBadge } from "@/components/common/common";
import { ReviewFindings } from "@/components/approvals/ReviewList";
import { useSafetyReviews } from "@/hooks/queries";
import { fmtDate, cn } from "@/lib/utils";

export default function SafetyReviewPage() {
  const q = useSafetyReviews();
  const [selected, setSelected] = useState<string>();

  return (
    <>
      <PageHeader title="Safety Review Centre" description="Safety status, findings and review history. Blocked stories remain blocked until a new passing review exists." />
      <QueryBoundary query={q} isEmpty={(d) => d.items.length === 0} empty={{ title: "No safety reviews yet" }}>
        {(d) => {
          const current = d.items.find((r) => r.id === selected) ?? d.items[0];
          const history = d.items.filter((r) => r.story_id === current.story_id);
          return (
            <div className="grid gap-4 lg:grid-cols-[22rem_1fr]">
              <Card className="self-start">
                <CardHeader>
                  <CardTitle>Reviews ({d.total})</CardTitle>
                </CardHeader>
                <ul className="max-h-[32rem] divide-y divide-border overflow-y-auto">
                  {d.items.map((r) => (
                    <li key={r.id}>
                      <button
                        type="button"
                        aria-pressed={r.id === current.id}
                        onClick={() => setSelected(r.id)}
                        className={cn("flex w-full items-center justify-between gap-2 px-4 py-2 text-left text-sm hover:bg-muted", r.id === current.id && "bg-muted")}
                      >
                        <span className="truncate">{r.story_id} · v{r.version ?? "?"}</span>
                        <StatusBadge status={r.status} />
                      </button>
                    </li>
                  ))}
                </ul>
              </Card>
              <div className="space-y-4">
                {current.status.toLowerCase().includes("block") && (
                  <p role="alert" className="rounded border border-primary/50 bg-primary/10 p-3 text-sm text-primary">
                    This story is blocked and cannot be approved or published until the backend records a passing safety review.
                  </p>
                )}
                <ReviewFindings review={current} />
                <Card>
                  <CardHeader>
                    <CardTitle>Review history for story {current.story_id}</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <ul className="space-y-1 text-sm">
                      {history.map((r) => (
                        <li key={r.id} className="flex items-center gap-3">
                          <span>v{r.version ?? "?"}</span>
                          <StatusBadge status={r.status} />
                          <span className="text-muted-foreground">{fmtDate(r.created_at)}</span>
                        </li>
                      ))}
                    </ul>
                  </CardContent>
                </Card>
              </div>
            </div>
          );
        }}
      </QueryBoundary>
    </>
  );
}
