import type { Finding, Review } from "@/schemas";
import { StatusBadge } from "@/components/common/common";
import { fmtDate, humanize } from "@/lib/utils";

export function FindingList({ findings }: { findings: Finding[] }) {
  return (
    <ul className="space-y-2">
      {findings.map((f, i) => (
        <li key={i} className="rounded border border-border/70 bg-background p-2 text-sm">
          <div className="flex flex-wrap items-center gap-2">
            {f.severity && <StatusBadge status={f.severity} />}
            {f.category && <span className="text-xs text-muted-foreground">{humanize(f.category)}</span>}
            <span>{f.issue ?? f.message}</span>
          </div>
          {f.location && <blockquote className="mt-2 border-l-2 border-primary/60 pl-3 text-muted-foreground">{f.location}</blockquote>}
          {f.explanation && <p className="mt-2 text-xs text-muted-foreground">{f.explanation}</p>}
          {f.recommendation && (
            <p className="mt-2 text-xs">
              <span className="text-muted-foreground">Recommended correction: </span>
              {f.recommendation}
            </p>
          )}
        </li>
      ))}
    </ul>
  );
}

export function ReviewFindings({ review }: { review: Review }) {
  return (
    <article className="rounded-md border border-border p-3">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="text-sm font-medium">{humanize(review.review_type)} review</h3>
        <StatusBadge status={review.status} />
        {review.version != null && <span className="text-xs text-muted-foreground">v{review.version}</span>}
        {review.is_valid === false && (
          <span className="rounded border border-warning/40 px-2 py-0.5 text-xs text-warning">Superseded{review.invalidated_reason ? `: ${review.invalidated_reason}` : ""}</span>
        )}
        {review.status.includes("HUMAN_REVIEW") && <span className="rounded border border-warning/40 px-2 py-0.5 text-xs text-warning">Human review required</span>}
        {review.coverage != null && <span className="text-xs text-muted-foreground">Coverage {(review.coverage * 100).toFixed(0)}%</span>}
        <span className="ml-auto text-xs text-muted-foreground">{fmtDate(review.created_at)}</span>
      </div>
      {review.findings.length === 0 ? <p className="mt-2 text-sm text-muted-foreground">No findings recorded.</p> : <div className="mt-3"><FindingList findings={review.findings} /></div>}
    </article>
  );
}
