import type { ReactNode } from "react";
import type { UseQueryResult } from "@tanstack/react-query";
import { AlertTriangle, Inbox, Loader2 } from "lucide-react";
import { Button, Card, Skeleton } from "@/components/ui/primitives";
import { cn, fmtNumber, humanize } from "@/lib/utils";
import { toApiError } from "@/services/client";

export const PageHeader = ({ title, description, actions }: { title: string; description?: string; actions?: ReactNode }) => (
  <header className="mb-6 flex flex-wrap items-end justify-between gap-3">
    <div>
      <h1 className="text-2xl font-semibold tracking-tight md:text-3xl">{title}</h1>
      {description && <p className="mt-1 text-sm text-muted-foreground">{description}</p>}
    </div>
    {actions}
  </header>
);

export const LoadingState = ({ label = "Loading" }: { label?: string }) => (
  <div role="status" aria-live="polite" className="space-y-3 p-4">
    <span className="sr-only">{label}…</span>
    <Skeleton className="h-5 w-1/3" />
    <Skeleton className="h-20 w-full" />
    <Skeleton className="h-20 w-full" />
  </div>
);

export const EmptyState = ({ title, hint }: { title: string; hint?: string }) => (
  <div className="flex flex-col items-center gap-2 px-4 py-10 text-center text-muted-foreground">
    <Inbox aria-hidden className="h-8 w-8" />
    <p className="font-medium text-foreground">{title}</p>
    {hint && <p className="max-w-md text-sm">{hint}</p>}
  </div>
);

export const ErrorState = ({ error, onRetry }: { error: unknown; onRetry?: () => void }) => {
  const e = toApiError(error);
  return (
    <div role="alert" className="flex flex-col items-center gap-2 px-4 py-8 text-center">
      <AlertTriangle aria-hidden className="h-8 w-8 text-primary" />
      <p className="font-medium">Something went wrong</p>
      <p className="max-w-md text-sm text-muted-foreground">{e.message}</p>
      {onRetry && (
        <Button variant="secondary" size="sm" onClick={onRetry}>
          Try again
        </Button>
      )}
    </div>
  );
};

/** Handles loading / error / empty uniformly, then renders children with the data. */
export function QueryBoundary<T>({
  query,
  isEmpty,
  empty,
  children,
}: {
  query: UseQueryResult<T>;
  isEmpty?: (data: T) => boolean;
  empty?: { title: string; hint?: string };
  children: (data: T) => ReactNode;
}) {
  if (query.isPending) return <LoadingState />;
  if (query.isError) return <ErrorState error={query.error} onRetry={() => void query.refetch()} />;
  if (isEmpty?.(query.data) && empty) return <EmptyState {...empty} />;
  return <>{children(query.data)}</>;
}

const tone = (s: string) => {
  const v = s.toLowerCase();
  if (/(fail|block|reject|error|cancel|critical|high|terminat|stale|uncertain)/.test(v)) return "border-primary/50 bg-primary/15 text-primary";
  if (/(complete|approved|passed|success|published|verified|done|consistent|low)/.test(v)) return "border-success/40 bg-success/10 text-success";
  if (/(run|progress|active|schedul|queued|medium|waiting|await|claimed|pending|planned|interrupt|needs_revision|human_review)/.test(v)) return "border-warning/40 bg-warning/10 text-warning";
  return "border-border bg-muted text-muted-foreground";
};

export const StatusBadge = ({ status, className }: { status?: string | null; className?: string }) => (
  <span className={cn("inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium", tone(status ?? ""), className)}>
    {status?.toLowerCase() === "running" && <Loader2 aria-hidden className="h-3 w-3 animate-spin motion-reduce:animate-none" />}
    {humanize(status)}
  </span>
);

export const StatCard = ({ label, value, hint }: { label: string; value: number | string | null | undefined; hint?: string }) => (
  <Card className="p-4">
    <p className="text-xs uppercase tracking-wide text-muted-foreground">{label}</p>
    <p className="mt-2 font-display text-3xl">{typeof value === "number" ? fmtNumber(value) : (value ?? "—")}</p>
    {hint && <p className="mt-1 text-xs text-muted-foreground">{hint}</p>}
  </Card>
);
