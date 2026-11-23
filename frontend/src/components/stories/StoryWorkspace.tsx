import { useState } from "react";
import { Button, Card, CardContent, CardHeader, CardTitle, Label, Tabs, TabsContent, TabsList, TabsTrigger, Textarea } from "@/components/ui/primitives";
import { ErrorState, LoadingState, QueryBoundary, StatusBadge } from "@/components/common/common";
import { ReviewFindings } from "@/components/approvals/ReviewList";
import { WorkflowProgress } from "@/components/workflow/WorkflowProgress";
import { AwaitingDecisions } from "@/components/workflow/AwaitingDecisions";
import {
  useAddRevision, useReviews, useRevisions, useStartStoryStep, useStory, useUpdateStory,
} from "@/hooks/queries";
import { PLATFORMS, type Revision, type Story } from "@/schemas";
import type { StoryStep } from "@/services/api";
import { useUiStore } from "@/stores/ui";
import { fmtDate, humanize } from "@/lib/utils";
import { Link } from "react-router-dom";

const countWords = (t: string) => (t.trim() ? t.trim().split(/\s+/).length : 0);

function Editor({ story, latest }: { story: Story; latest?: Revision }) {
  const { drafts, setDraft, clearDraft } = useUiStore();
  const base = latest?.text ?? "";
  const draft = drafts[story.id];
  const [text, setText] = useState(draft ?? base);
  const save = useAddRevision(story.id);
  const dirty = text !== base;

  return (
    <div className="space-y-3">
      {draft !== undefined && draft !== base && <p className="text-xs text-warning">Unsaved local draft restored. Saving creates a new backend revision.</p>}
      <Label htmlFor="editor">Story text{latest ? ` (editing from v${latest.version})` : ""}</Label>
      <Textarea
        id="editor"
        className="min-h-[24rem] font-serif text-base leading-relaxed"
        value={text}
        onChange={(e) => {
          setText(e.target.value);
          setDraft(story.id, e.target.value);
        }}
      />
      <div className="flex flex-wrap items-center gap-4 text-sm text-muted-foreground">
        <span>Actual words: {countWords(text)}</span>
        <span>Target: {story.target_word_count ?? "—"}</span>
        <span>Last saved: {story.current_revision?.word_count ?? latest?.word_count ?? "—"}</span>
        <Button
          className="ml-auto"
          disabled={!dirty || !text.trim() || save.isPending}
          onClick={() => save.mutate({ text, kind: "final" }, { onSuccess: () => clearDraft(story.id) })}
        >
          Save as new revision
        </Button>
      </div>
    </div>
  );
}

function Revisions({ storyId }: { storyId: string }) {
  const q = useRevisions(storyId);
  const restore = useAddRevision(storyId);
  const [open, setOpen] = useState<number | null>(null);
  return (
    <QueryBoundary query={q} isEmpty={(d) => d.items.length === 0} empty={{ title: "No revisions yet" }}>
      {(d) => (
        <ul className="space-y-2">
          {[...d.items].sort((a, b) => b.version - a.version).map((r) => (
            <li key={r.version} className="rounded-md border border-border p-3 text-sm">
              <div className="flex flex-wrap items-center gap-3">
                <strong>v{r.version}</strong>
                <span className="text-muted-foreground">{humanize(r.kind)} · {r.author ?? "unknown"} · {fmtDate(r.created_at)}</span>
                {r.content_hash && <code className="text-xs text-muted-foreground">{r.content_hash.slice(0, 8)}</code>}
                <Button size="sm" variant="ghost" className="ml-auto" aria-expanded={open === r.version} onClick={() => setOpen(open === r.version ? null : r.version)}>
                  {open === r.version ? "Hide" : "View"}
                </Button>
                <Button size="sm" variant="secondary" disabled={!r.text || restore.isPending} onClick={() => restore.mutate({ text: r.text!, kind: "final" })}>
                  Restore as new
                </Button>
              </div>
              {open === r.version && <pre className="mt-3 max-h-80 overflow-auto whitespace-pre-wrap rounded bg-background p-3 font-serif">{r.text ?? "Text not provided by the API."}</pre>}
            </li>
          ))}
        </ul>
      )}
    </QueryBoundary>
  );
}

const STEPS: { step: StoryStep; label: string }[] = [
  { step: "humanise", label: "Humanise" },
  { step: "continuity", label: "Continuity review" },
  { step: "editorial", label: "Editorial review" },
  { step: "safety", label: "Safety review" },
];

function Reviews({ storyId, onStarted }: { storyId: string; onStarted: (workflowId: string) => void }) {
  const reviews = useReviews(storyId);
  const run = useStartStoryStep(storyId);
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2">
        {STEPS.map(({ step, label }) => (
          <Button key={step} variant="secondary" disabled={run.isPending} onClick={() => run.mutate(step, { onSuccess: (wf) => onStarted(wf.workflow_id) })}>
            Run {label.toLowerCase()}
          </Button>
        ))}
      </div>
      <QueryBoundary query={reviews} isEmpty={(d) => d.items.length === 0} empty={{ title: "No reviews yet", hint: "Run a review above. New revisions invalidate earlier reviews." }}>
        {(d) => (
          <div className="space-y-3">
            {d.items.map((r) => (
              <ReviewFindings key={r.id} review={r} />
            ))}
          </div>
        )}
      </QueryBoundary>
    </div>
  );
}

function Details({ story }: { story: Story }) {
  const update = useUpdateStory(story.id);
  const meta = story.metadata ?? {};
  const [synopsis, setSynopsis] = useState(typeof meta.synopsis === "string" ? meta.synopsis : "");
  const [series, setSeries] = useState(typeof meta.series_details === "string" ? meta.series_details : "");
  return (
    <div className="space-y-4">
      <div>
        <Label htmlFor="synopsis">Synopsis</Label>
        <Textarea id="synopsis" value={synopsis} onChange={(e) => setSynopsis(e.target.value)} />
      </div>
      <div>
        <Label htmlFor="series">Series details {story.series_id ? `(series ${story.series_id}${story.episode_number ? `, episode ${story.episode_number}` : ""})` : ""}</Label>
        <Textarea id="series" value={series} onChange={(e) => setSeries(e.target.value)} />
      </div>
      <Button disabled={update.isPending} onClick={() => update.mutate({ ...meta, synopsis, series_details: series })}>
        Save details
      </Button>
    </div>
  );
}

export function StoryWorkspace({ storyId }: { storyId: string }) {
  const story = useStory(storyId);
  const revisions = useRevisions(storyId);
  const [workflowId, setWorkflowId] = useState<string>();

  if (story.isPending) return <LoadingState label="Loading story" />;
  if (story.isError) return <ErrorState error={story.error} onRetry={() => void story.refetch()} />;
  const s = story.data;
  const latest = revisions.data?.items.reduce<Revision | undefined>((a, r) => (!a || r.version > a.version ? r : a), undefined);

  return (
    <Card>
      <CardHeader className="flex-wrap">
        <div>
          <CardTitle className="font-display text-xl">{s.title}</CardTitle>
          <p className="text-xs text-muted-foreground">
            ID {s.id} · {humanize(s.story_type)} · v{s.current_version ?? latest?.version ?? "—"}
          </p>
        </div>
        <StatusBadge status={s.status} />
      </CardHeader>
      <CardContent>
        {s.review_state && (
          <div className="mb-4 flex flex-wrap items-center gap-3 text-sm" aria-label="Review state">
            <span className="text-muted-foreground">Editorial</span> <StatusBadge status={s.review_state.editorial_status ?? "NOT_REVIEWED"} />
            <span className="text-muted-foreground">Safety</span> <StatusBadge status={s.review_state.safety_status ?? "NOT_REVIEWED"} />
            <StatusBadge status={s.review_state.approved ? "approved" : "not approved"} />
            {s.review_state.blockers && s.review_state.blockers.length > 0 && (
              <ul className="w-full list-disc pl-5 text-xs text-muted-foreground">
                {s.review_state.blockers.map((b) => (
                  <li key={b}>{b}</li>
                ))}
              </ul>
            )}
          </div>
        )}
        <AwaitingDecisions storyId={s.id} />
        <Tabs defaultValue="editor">
          <TabsList aria-label="Story sections">
            <TabsTrigger value="editor">Editor</TabsTrigger>
            <TabsTrigger value="revisions">Revisions</TabsTrigger>
            <TabsTrigger value="reviews">Reviews</TabsTrigger>
            <TabsTrigger value="details">Synopsis &amp; series</TabsTrigger>
            <TabsTrigger value="distribution">Distribution</TabsTrigger>
          </TabsList>
          <TabsContent value="editor">
            {revisions.isPending ? <LoadingState /> : <Editor key={latest?.version ?? 0} story={s} latest={latest} />}
          </TabsContent>
          <TabsContent value="revisions">
            <Revisions storyId={s.id} />
          </TabsContent>
          <TabsContent value="reviews">
            <Reviews storyId={s.id} onStarted={setWorkflowId} />
          </TabsContent>
          <TabsContent value="details">
            <Details key={s.id} story={s} />
          </TabsContent>
          <TabsContent value="distribution">
            <ul className="grid gap-2 sm:grid-cols-2">
              {PLATFORMS.map((p) => (
                <li key={p.id}>
                  <Link className="block rounded-md border border-border p-3 text-sm hover:bg-muted" to={`/distribution?story=${s.id}&platform=${p.id}`}>
                    Preview and edit {p.label} content
                  </Link>
                </li>
              ))}
            </ul>
          </TabsContent>
        </Tabs>
        {workflowId && (
          <div className="mt-6 border-t border-border pt-4">
            <h3 className="mb-2 text-sm font-medium">Workflow progress</h3>
            <WorkflowProgress workflowId={workflowId} />
          </div>
        )}
      </CardContent>
    </Card>
  );
}
