import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Button, Card, CardContent, Label, Select, Tabs, TabsContent, TabsList, TabsTrigger, Textarea } from "@/components/ui/primitives";
import { EmptyState, PageHeader, QueryBoundary } from "@/components/common/common";
import { useDistribution, useSaveDistribution, useStories } from "@/hooks/queries";
import { PLATFORMS, type Distribution } from "@/schemas";
import { toApiError } from "@/services/client";
import { humanize } from "@/lib/utils";

/** Platform payloads are free-form JSON written by the distribution agent: edit as JSON, preview its text fields. */
function PlatformEditor({ storyId, platform, data }: { storyId: string; platform: string; data: Pick<Distribution, "payload" | "status" | "version"> }) {
  const save = useSaveDistribution(storyId, platform);
  const original = JSON.stringify(data.payload, null, 2);
  const [text, setText] = useState(original);
  let parsed: Record<string, unknown> | null = null;
  let parseError: string | null = null;
  try {
    const v: unknown = JSON.parse(text);
    if (v && typeof v === "object" && !Array.isArray(v)) parsed = v as Record<string, unknown>;
    else parseError = "Payload must be a JSON object.";
  } catch (e) {
    parseError = e instanceof Error ? e.message : "Invalid JSON";
  }
  const strings = Object.entries(parsed ?? {}).filter(([, v]) => typeof v === "string") as [string, string][];
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <div className="space-y-3">
        <p className="text-xs text-muted-foreground">
          {data.version != null ? `Version ${data.version}` : "No content stored yet"} {data.status ? `· ${humanize(data.status)}` : ""}
        </p>
        <Label htmlFor={`p-${platform}`}>Payload (JSON)</Label>
        <Textarea id={`p-${platform}`} className="min-h-[18rem] font-mono text-xs" value={text} onChange={(e) => setText(e.target.value)} aria-invalid={!!parseError} />
        {parseError && <p role="alert" className="text-xs text-primary">{parseError}</p>}
        <Button disabled={!parsed || text === original || save.isPending} onClick={() => parsed && save.mutate({ payload: parsed })}>
          Save content
        </Button>
      </div>
      <section aria-label="Preview" className="rounded-md border border-border bg-background p-4">
        <p className="mb-2 text-xs uppercase tracking-wide text-muted-foreground">Preview</p>
        {strings.length === 0 ? (
          <p className="text-sm">Nothing to preview.</p>
        ) : (
          strings.map(([k, v]) => (
            <div key={k} className="mb-3">
              <p className="text-xs text-muted-foreground">{humanize(k)}</p>
              <p className="whitespace-pre-wrap text-sm leading-relaxed">{v}</p>
            </div>
          ))
        )}
      </section>
    </div>
  );
}

function PlatformPanel({ storyId, platform }: { storyId: string; platform: string }) {
  const q = useDistribution(storyId, platform);
  // 404 simply means nothing has been generated for the current version yet; PUT creates it.
  if (q.isError && toApiError(q.error).status === 404) {
    return (
      <div className="space-y-3">
        <EmptyState title="No distribution content for this version yet" hint="Run the distribution workflow, or write a payload below." />
        <PlatformEditor key={`${storyId}-${platform}-new`} storyId={storyId} platform={platform} data={{ payload: {} }} />
      </div>
    );
  }
  return (
    <QueryBoundary query={q}>
      {(d) => <PlatformEditor key={`${storyId}-${platform}-${d.version}-${JSON.stringify(d.payload).length}`} storyId={storyId} platform={platform} data={d} />}
    </QueryBoundary>
  );
}

export default function DistributionPage() {
  const stories = useStories();
  const [params, setParams] = useSearchParams();
  const storyId = params.get("story") ?? "";
  const platform = params.get("platform") ?? PLATFORMS[0].id;
  const set = (patch: Record<string, string>) => setParams({ story: storyId, platform, ...patch });

  return (
    <>
      <PageHeader title="Distribution Plan" description="Platform-specific content for each approved story." />
      <Card className="mb-4">
        <CardContent>
          <Label htmlFor="dist-story">Story</Label>
          <QueryBoundary query={stories} isEmpty={(d) => d.items.length === 0} empty={{ title: "No stories available" }}>
            {(d) => (
              <Select id="dist-story" value={storyId} onChange={(e) => set({ story: e.target.value })}>
                <option value="">Select a story…</option>
                {d.items.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.title}
                  </option>
                ))}
              </Select>
            )}
          </QueryBoundary>
        </CardContent>
      </Card>
      {!storyId ? (
        <EmptyState title="Select a story to preview its distribution content" />
      ) : (
        <Tabs value={platform} onValueChange={(v) => set({ platform: v })}>
          <TabsList aria-label="Platforms">
            {PLATFORMS.map((p) => (
              <TabsTrigger key={p.id} value={p.id}>
                {p.label}
              </TabsTrigger>
            ))}
          </TabsList>
          {PLATFORMS.map((p) => (
            <TabsContent key={p.id} value={p.id}>
              <PlatformPanel storyId={storyId} platform={p.id} />
            </TabsContent>
          ))}
        </Tabs>
      )}
    </>
  );
}
