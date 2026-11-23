import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { toast } from "sonner";
import { Button, FieldError, Input, Label, Select, Textarea } from "@/components/ui/primitives";
import { useCreateStory, useProfiles, useStartWorkflow } from "@/hooks/queries";

/** Backend profile lookup normalises names this way (story_profile_service._norm). */
export const profileKey = (name: string) => name.trim().toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "");

const schema = z.object({
  title: z.string().trim().min(3, "Title must be at least 3 characters"),
  story_type: z.string().min(1, "Choose a story type"),
  target_word_count: z.preprocess(
    (v) => (v === "" || v == null || Number.isNaN(v) ? undefined : v),
    z.number({ invalid_type_error: "Enter a number" }).int("Whole words only").positive("Must be positive").optional(),
  ),
  brief: z.string().optional(),
  generate: z.boolean(),
});
type FormValues = z.input<typeof schema>;

export function CreateStoryForm({ onCreated }: { onCreated: (storyId: string) => void }) {
  const profiles = useProfiles();
  const create = useCreateStory();
  const start = useStartWorkflow();
  const {
    register,
    handleSubmit,
    watch,
    formState: { errors },
  } = useForm<FormValues>({ resolver: zodResolver(schema), defaultValues: { title: "", story_type: "", brief: "", generate: true } });

  const profile = profiles.data?.items.find((p) => profileKey(p.name) === watch("story_type"));

  const onSubmit = handleSubmit(async (v) => {
    const { generate, brief, ...rest } = schema.parse(v);
    const metadata = brief ? { brief } : {};
    // POST /stories body: {title, genre, story_type, target_word_count, metadata}
    const story = await create.mutateAsync({ ...rest, genre: "horror", metadata });
    toast.success(`Story "${story.title}" created`);
    if (generate) {
      // POST /workflows body: {workflow_type, story_id, params}
      await start.mutateAsync({
        workflow_type: "story_generation",
        story_id: story.id,
        params: { story_type: rest.story_type, target_word_count: rest.target_word_count, brief },
      });
    }
    onCreated(story.id);
  });

  return (
    <form onSubmit={(e) => void onSubmit(e).catch(() => undefined)} className="space-y-4" noValidate aria-label="Create story">
      <div>
        <Label htmlFor="cs-title">Title</Label>
        <Input id="cs-title" aria-invalid={!!errors.title} {...register("title")} />
        <FieldError message={errors.title?.message} />
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        <div>
          <Label htmlFor="cs-type">Story type</Label>
          <Select id="cs-type" aria-invalid={!!errors.story_type} {...register("story_type")}>
            <option value="">Select…</option>
            {profiles.data?.items.map((p) => (
              <option key={p.name} value={profileKey(p.name)}>
                {p.name}
              </option>
            ))}
          </Select>
          <FieldError message={errors.story_type?.message} />
          {profiles.isError && <p className="mt-1 text-xs text-primary">Could not load story profiles.</p>}
        </div>
        <div>
          <Label htmlFor="cs-words">Target word count</Label>
          <Input id="cs-words" type="number" inputMode="numeric" aria-invalid={!!errors.target_word_count} aria-describedby="cs-words-hint" {...register("target_word_count", { valueAsNumber: true })} />
          <p id="cs-words-hint" className="mt-1 text-xs text-muted-foreground">
            {profile ? `Profile: ${profile.min ?? "?"}–${profile.max ?? "?"} words, target ${profile.target ?? "?"}. The backend enforces limits.` : "Select a story type to see its word-count profile."}
          </p>
          <FieldError message={errors.target_word_count?.message} />
        </div>
      </div>
      <div>
        <Label htmlFor="cs-brief">Brief (optional)</Label>
        <Textarea id="cs-brief" {...register("brief")} />
      </div>
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" className="accent-[hsl(var(--primary))]" {...register("generate")} />
        Start the story generation workflow immediately
      </label>
      <Button type="submit" disabled={create.isPending || start.isPending}>
        {create.isPending || start.isPending ? "Creating…" : "Create story"}
      </Button>
    </form>
  );
}
