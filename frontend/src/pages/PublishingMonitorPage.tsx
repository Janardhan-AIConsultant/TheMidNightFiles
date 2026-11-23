import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { ExternalLink } from "lucide-react";
import { Button, Card, CardContent, CardHeader, CardTitle, FieldError, Input, Label, Select, Table, Td, Th } from "@/components/ui/primitives";
import { PageHeader, QueryBoundary, StatusBadge } from "@/components/common/common";
import { useEnqueue, usePublishQueue, useQueueAction } from "@/hooks/queries";
import { NOT_CANCELLABLE, PUBLISH_PLATFORMS, QUEUE_STATUSES, RETRYABLE } from "@/schemas";
import { useState } from "react";
import { fmtDate, humanize } from "@/lib/utils";

const schema = z.object({
  story_id: z.string().trim().min(1, "Story ID is required"),
  version: z.coerce.number({ invalid_type_error: "Version must be a number" }).int().positive("Version must be positive"),
  platform: z.string().min(1, "Choose a platform"),
  scheduled_for: z.string().optional(),
});
type Values = z.input<typeof schema>;

function ScheduleForm() {
  const enqueue = useEnqueue();
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<Values>({ resolver: zodResolver(schema), defaultValues: { story_id: "", platform: "" } });
  const onSubmit = handleSubmit((v) => {
    const p = schema.parse(v);
    enqueue.mutate({ ...p, scheduled_for: p.scheduled_for ? new Date(p.scheduled_for).toISOString() : undefined }, { onSuccess: () => reset() });
  });
  return (
    <form onSubmit={(e) => void onSubmit(e)} noValidate aria-label="Schedule publication" className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5 lg:items-start">
      <div>
        <Label htmlFor="q-story">Story ID</Label>
        <Input id="q-story" aria-invalid={!!errors.story_id} {...register("story_id")} />
        <FieldError message={errors.story_id?.message} />
      </div>
      <div>
        <Label htmlFor="q-version">Version</Label>
        <Input id="q-version" type="number" aria-invalid={!!errors.version} {...register("version")} />
        <FieldError message={errors.version?.message} />
      </div>
      <div>
        <Label htmlFor="q-platform">Platform</Label>
        <Select id="q-platform" aria-invalid={!!errors.platform} {...register("platform")}>
          <option value="">Select…</option>
          {PUBLISH_PLATFORMS.map((p) => (
            <option key={p.id} value={p.id}>
              {p.label}
            </option>
          ))}
        </Select>
        <FieldError message={errors.platform?.message} />
      </div>
      <div>
        <Label htmlFor="q-when">Scheduled for (optional)</Label>
        <Input id="q-when" type="datetime-local" aria-invalid={!!errors.scheduled_for} {...register("scheduled_for")} />
        <FieldError message={errors.scheduled_for?.message} />
      </div>
      <Button type="submit" className="lg:mt-5" disabled={enqueue.isPending}>
        Schedule
      </Button>
    </form>
  );
}

export default function PublishingMonitorPage() {
  const [status, setStatus] = useState("");
  const q = usePublishQueue(status);
  const act = useQueueAction();
  return (
    <>
      <PageHeader title="Publishing Monitor" description="Queue state, retries and verification. Authorisation is enforced by the backend." />
      <div className="space-y-4">
        <Card>
          <CardHeader>
            <CardTitle>Schedule a publication</CardTitle>
          </CardHeader>
          <CardContent>
            <ScheduleForm />
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Queue</CardTitle>
          </CardHeader>
          <div className="border-b border-border p-4 sm:w-64">
            <Label htmlFor="q-status">Status</Label>
            <Select id="q-status" value={status} onChange={(e) => setStatus(e.target.value)}>
              <option value="">All statuses</option>
              {QUEUE_STATUSES.map((s) => (
                <option key={s} value={s}>
                  {humanize(s)}
                </option>
              ))}
            </Select>
          </div>
          <QueryBoundary query={q} isEmpty={(d) => d.items.length === 0} empty={{ title: "The publishing queue is empty" }}>
            {(d) => (
              <Table>
                <thead>
                  <tr>
                    <Th>Story</Th>
                    <Th>Platform</Th>
                    <Th>Ver.</Th>
                    <Th>Scheduled</Th>
                    <Th>Status</Th>
                    <Th>Attempts</Th>
                    <Th>Approval</Th>
                    <Th>Result</Th>
                    <Th>Actions</Th>
                  </tr>
                </thead>
                <tbody>
                  {d.items.map((i) => (
                    <tr key={i.id}>
                      <Td>{i.story_id}</Td>
                      <Td>{humanize(i.platform)}</Td>
                      <Td>{i.version ?? "—"}</Td>
                      <Td>{fmtDate(i.scheduled_at)}</Td>
                      <Td>
                        <StatusBadge status={i.status} />
                        {i.last_error && <p className="mt-1 max-w-xs text-xs text-primary">{i.last_error}</p>}
                      </Td>
                      <Td>{i.attempts ?? 0}</Td>
                      <Td>{i.approval_id != null ? `#${i.approval_id}` : "—"}</Td>
                      <Td>
                        {i.external_url && (
                          <a href={i.external_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-primary hover:underline">
                            Published <ExternalLink aria-hidden className="h-3 w-3" />
                          </a>
                        )}
                        {i.screenshot_ref && <p className="text-xs text-muted-foreground">Screenshot: {i.screenshot_ref}</p>}
                        {i.manual_fallback != null && i.manual_fallback !== "" && <p className="text-xs text-warning">Manual fallback: {typeof i.manual_fallback === "string" ? i.manual_fallback : JSON.stringify(i.manual_fallback)}</p>}
                      </Td>
                      <Td>
                        <div className="flex gap-1">
                          <Button size="sm" variant="secondary" disabled={act.isPending || !RETRYABLE.includes(i.status)} aria-label={`Retry job ${i.id} ${i.story_id}`} onClick={() => act.mutate({ id: i.id, action: "retry" })}>
                            Retry
                          </Button>
                          <Button size="sm" variant="destructive" disabled={act.isPending || NOT_CANCELLABLE.includes(i.status)} aria-label={`Cancel job ${i.id} ${i.story_id}`} onClick={() => act.mutate({ id: i.id, action: "cancel" })}>
                            Cancel
                          </Button>
                        </div>
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
