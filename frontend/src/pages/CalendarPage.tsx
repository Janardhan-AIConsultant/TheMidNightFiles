import { useMemo, useState } from "react";
import FullCalendar from "@fullcalendar/react";
import dayGridPlugin from "@fullcalendar/daygrid";
import timeGridPlugin from "@fullcalendar/timegrid";
import interactionPlugin from "@fullcalendar/interaction";
import type { EventDropArg } from "@fullcalendar/core";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { Link } from "react-router-dom";
import { Button, Card, CardContent, CardHeader, CardTitle, FieldError, Input, Label, Select } from "@/components/ui/primitives";
import { PageHeader, QueryBoundary, StatusBadge } from "@/components/common/common";
import { useCalendar, useCreateCalendarEntry, useReschedule } from "@/hooks/queries";
import type { CalendarEntry } from "@/schemas";
import { useUiStore } from "@/stores/ui";
import { fmtDate, humanize, parseUtc } from "@/lib/utils";

const createSchema = z.object({
  topic: z.string().trim().min(1, "Topic is required").max(300, "At most 300 characters"),
  planned_date: z.string().min(1, "Choose a date and time"),
  genre: z.string().optional(),
  story_type: z.string().optional(),
  story_id: z.string().optional(),
});
type CreateValues = z.input<typeof createSchema>;

/** POST /calendar body: {planned_date, topic, genre?, story_type, story_id?, details}. */
export function CreateEntryForm() {
  const create = useCreateCalendarEntry();
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<CreateValues>({ resolver: zodResolver(createSchema), defaultValues: { topic: "", planned_date: "", genre: "", story_type: "standalone", story_id: "" } });
  const onSubmit = handleSubmit((v) => {
    const p = createSchema.parse(v);
    create.mutate(
      {
        topic: p.topic,
        planned_date: new Date(p.planned_date).toISOString(),
        genre: p.genre || undefined,
        story_type: p.story_type || undefined,
        story_id: p.story_id?.trim() || undefined,
      },
      { onSuccess: () => reset() },
    );
  });
  return (
    <form onSubmit={(e) => void onSubmit(e)} noValidate aria-label="Create calendar entry" className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5 lg:items-start">
      <div className="lg:col-span-2">
        <Label htmlFor="ce-topic">Topic</Label>
        <Input id="ce-topic" aria-invalid={!!errors.topic} {...register("topic")} />
        <FieldError message={errors.topic?.message} />
      </div>
      <div>
        <Label htmlFor="ce-date">Planned date</Label>
        <Input id="ce-date" type="datetime-local" aria-invalid={!!errors.planned_date} {...register("planned_date")} />
        <FieldError message={errors.planned_date?.message} />
      </div>
      <div>
        <Label htmlFor="ce-genre">Genre (optional)</Label>
        <Input id="ce-genre" {...register("genre")} />
      </div>
      <div>
        <Label htmlFor="ce-story">Story ID (optional)</Label>
        <Input id="ce-story" {...register("story_id")} />
      </div>
      <Button type="submit" disabled={create.isPending} className="lg:col-span-5 lg:justify-self-start">
        Add to calendar
      </Button>
    </form>
  );
}

function CalendarView({ entries }: { entries: CalendarEntry[] }) {
  const { calendarFilters: f, setCalendarFilter } = useUiStore();
  const reschedule = useReschedule();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [newDate, setNewDate] = useState("");

  const statuses = useMemo(() => [...new Set(entries.map((e) => e.status).filter(Boolean))] as string[], [entries]);
  const genres = useMemo(() => [...new Set(entries.map((e) => e.genre).filter(Boolean))] as string[], [entries]);
  const visible = entries.filter((e) => (!f.status || e.status === f.status) && (!f.genre || e.genre === f.genre));
  const selected = entries.find((e) => e.id === selectedId);

  const onDrop = (arg: EventDropArg) => {
    reschedule.mutate({ id: arg.event.id, planned_date: arg.event.start!.toISOString() }, { onError: () => arg.revert() });
  };

  return (
    <div className="grid gap-4 xl:grid-cols-[1fr_20rem]">
      <Card>
        <CardContent>
          <div className="mb-4 grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div>
              <Label htmlFor="f-status">Status</Label>
              <Select id="f-status" value={f.status} onChange={(e) => setCalendarFilter("status", e.target.value)}>
                <option value="">All statuses</option>
                {statuses.map((s) => (
                  <option key={s} value={s}>
                    {humanize(s)}
                  </option>
                ))}
              </Select>
            </div>
            <div>
              <Label htmlFor="f-genre">Genre</Label>
              <Select id="f-genre" value={f.genre} onChange={(e) => setCalendarFilter("genre", e.target.value)}>
                <option value="">All genres</option>
                {genres.map((g) => (
                  <option key={g} value={g}>
                    {g}
                  </option>
                ))}
              </Select>
            </div>
          </div>
          {visible.length === 0 && <p className="mb-3 text-sm text-muted-foreground">No entries match the current filters.</p>}
          <FullCalendar
            plugins={[dayGridPlugin, timeGridPlugin, interactionPlugin]}
            initialView="dayGridMonth"
            headerToolbar={{ left: "prev,next today", center: "title", right: "dayGridMonth,timeGridWeek" }}
            buttonText={{ today: "Today", month: "Month", week: "Week" }}
            height="auto"
            editable
            eventStartEditable={true}
            events={visible.map((e) => ({
              id: e.id,
              title: e.topic,
              start: parseUtc(e.planned_date),
              editable: e.status === "PLANNED",
            }))}
            eventDrop={onDrop}
            eventClick={(arg) => {
              setSelectedId(arg.event.id);
              setNewDate(arg.event.start?.toISOString().slice(0, 10) ?? "");
            }}
          />
        </CardContent>
      </Card>

      <Card aria-live="polite">
        <CardHeader>
          <CardTitle>Entry details</CardTitle>
        </CardHeader>
        <CardContent>
          {!selected ? (
            <p className="text-sm text-muted-foreground">Select an event to view details or drag a planned one to reschedule.</p>
          ) : (
            <div className="space-y-3 text-sm">
              <p className="font-display text-lg">{selected.topic}</p>
              <dl className="grid grid-cols-2 gap-1">
                <dt className="text-muted-foreground">Genre</dt>
                <dd>{selected.genre ?? "—"}</dd>
                <dt className="text-muted-foreground">Story type</dt>
                <dd>{humanize(selected.story_type)}</dd>
                <dt className="text-muted-foreground">Planned</dt>
                <dd>{fmtDate(selected.planned_date)}</dd>
                <dt className="text-muted-foreground">Status</dt>
                <dd>
                  <StatusBadge status={selected.status} />
                </dd>
              </dl>
              {selected.status === "PLANNED" && (
                <div>
                  <Label htmlFor="resched">Reschedule to</Label>
                  <div className="flex gap-2">
                    <Input id="resched" type="date" value={newDate} onChange={(e) => setNewDate(e.target.value)} />
                    <Button size="sm" disabled={!newDate || reschedule.isPending} onClick={() => reschedule.mutate({ id: selected.id, planned_date: new Date(`${newDate}T${selected.planned_date.slice(11, 19) || "00:00:00"}Z`).toISOString() })}>
                      Save
                    </Button>
                  </div>
                </div>
              )}
              {selected.story_id && (
                <Link className="text-primary hover:underline" to={`/studio/${selected.story_id}`}>
                  Open in Content Studio
                </Link>
              )}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

export default function CalendarPage() {
  const q = useCalendar();
  return (
    <>
      <PageHeader title="Content Calendar" description="Editorial plan. Only PLANNED entries can be rescheduled; the backend enforces this." />
      <div className="space-y-4">
        <Card>
          <CardHeader>
            <CardTitle>Plan new content</CardTitle>
          </CardHeader>
          <CardContent>
            <CreateEntryForm />
          </CardContent>
        </Card>
        <QueryBoundary query={q} isEmpty={(d) => d.items.length === 0} empty={{ title: "No calendar entries", hint: "Add a planned topic above." }}>
          {(d) => <CalendarView entries={d.items} />}
        </QueryBoundary>
      </div>
    </>
  );
}
