import { useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/primitives";
import { PageHeader, QueryBoundary, StatusBadge } from "@/components/common/common";
import { ReviewDecisionPanel } from "@/components/approvals/ReviewDecisionPanel";
import { ReviewFindings } from "@/components/approvals/ReviewList";
import { AwaitingDecisions } from "@/components/workflow/AwaitingDecisions";
import { usePendingApprovals, useReviews } from "@/hooks/queries";
import type { PendingApproval } from "@/schemas";
import { cn } from "@/lib/utils";

function Detail({ item, onDone }: { item: PendingApproval; onDone: () => void }) {
  const reviews = useReviews(item.story_id);
  return (
    <Card>
      <CardHeader>
        <CardTitle>
          {item.title ?? `Story ${item.story_id}`} <span className="text-sm text-muted-foreground">· ID {item.story_id} · v{item.version}</span>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-6">
        <section aria-label="Reviews">
          <h3 className="mb-2 text-sm font-medium">Editorial, continuity and safety reviews</h3>
          <QueryBoundary query={reviews} isEmpty={(d) => d.items.length === 0} empty={{ title: "No reviews recorded", hint: "The backend will refuse approval until required reviews exist for this version." }}>
            {(d) => (
              <div className="space-y-3">
                {[...d.items]
                  .sort((a, b) => Number(b.version === item.version) - Number(a.version === item.version) || (b.version ?? 0) - (a.version ?? 0))
                  .map((r) => (
                    <div key={r.id} className={cn(r.version !== item.version && "opacity-70")}>
                      {r.version !== item.version && <p className="mb-1 text-xs text-muted-foreground">History (earlier version)</p>}
                      <ReviewFindings review={r} />
                    </div>
                  ))}
              </div>
            )}
          </QueryBoundary>
        </section>
        <section aria-label="Workflow decisions">
          <AwaitingDecisions storyId={item.story_id} />
        </section>
        <section aria-label="Decision">
          <h3 className="mb-2 text-sm font-medium">Direct approval</h3>
          <p className="mb-2 text-xs text-muted-foreground">
            Editorial {item.editorial_status ?? "not reviewed"} · Safety {item.safety_status ?? "not reviewed"}. Eligibility is enforced by the backend.
          </p>
          <ReviewDecisionPanel storyId={item.story_id} version={item.version} onDone={onDone} />
        </section>
      </CardContent>
    </Card>
  );
}

export default function ApprovalCentrePage() {
  const pending = usePendingApprovals();
  const [selected, setSelected] = useState<string>();

  return (
    <>
      <PageHeader title="Approval Centre" description="Human approval gate. Eligibility is always enforced by the backend." />
      <QueryBoundary query={pending} isEmpty={(d) => d.items.length === 0} empty={{ title: "Nothing awaiting approval" }}>
        {(d) => {
          const key = (p: PendingApproval) => `${p.story_id}:${p.version}`;
          const item = d.items.find((p) => key(p) === selected) ?? d.items[0];
          return (
            <div className="grid gap-4 lg:grid-cols-[18rem_1fr]">
              <Card className="self-start">
                <CardHeader>
                  <CardTitle>Pending ({d.total})</CardTitle>
                </CardHeader>
                <ul className="divide-y divide-border">
                  {d.items.map((p) => (
                    <li key={key(p)}>
                      <button
                        type="button"
                        aria-pressed={key(p) === key(item)}
                        onClick={() => setSelected(key(p))}
                        className={cn("flex w-full items-center justify-between gap-2 px-4 py-2 text-left text-sm hover:bg-muted", key(p) === key(item) && "bg-muted")}
                      >
                        <span className="truncate">{p.title ?? p.story_id} · v{p.version}</span>
                        {p.story_status && <StatusBadge status={p.story_status} />}
                      </button>
                    </li>
                  ))}
                </ul>
              </Card>
              <Detail key={key(item)} item={item} onDone={() => setSelected(undefined)} />
            </div>
          );
        }}
      </QueryBoundary>
    </>
  );
}
