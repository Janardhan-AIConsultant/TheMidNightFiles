import { Link, useNavigate, useParams } from "react-router-dom";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/primitives";
import { PageHeader, QueryBoundary, StatusBadge } from "@/components/common/common";
import { CreateStoryForm } from "@/components/stories/CreateStoryForm";
import { StoryWorkspace } from "@/components/stories/StoryWorkspace";
import { useStories } from "@/hooks/queries";
import { cn } from "@/lib/utils";

export default function ContentStudioPage() {
  const { storyId } = useParams();
  const navigate = useNavigate();
  const stories = useStories();

  return (
    <>
      <PageHeader title="Content Studio" description="Create, edit, version and review stories. Every save creates an immutable backend revision." />
      <div className="grid gap-4 lg:grid-cols-[18rem_1fr]">
        <Card className="self-start">
          <CardHeader>
            <CardTitle>Stories</CardTitle>
            <Link to="/studio" className="text-xs text-primary hover:underline">
              New story
            </Link>
          </CardHeader>
          <QueryBoundary query={stories} isEmpty={(d) => d.items.length === 0} empty={{ title: "No stories yet", hint: "Create the first one." }}>
            {(d) => (
              <ul className="max-h-[28rem] divide-y divide-border overflow-y-auto">
                {d.items.map((s) => (
                  <li key={s.id}>
                    <Link
                      to={`/studio/${s.id}`}
                      aria-current={s.id === storyId ? "page" : undefined}
                      className={cn("flex items-center justify-between gap-2 px-4 py-2 text-sm hover:bg-muted", s.id === storyId && "bg-muted")}
                    >
                      <span className="truncate">{s.title}</span>
                      <StatusBadge status={s.status} />
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </QueryBoundary>
        </Card>
        {storyId ? (
          <StoryWorkspace key={storyId} storyId={storyId} />
        ) : (
          <Card>
            <CardHeader>
              <CardTitle>Create a story</CardTitle>
            </CardHeader>
            <CardContent>
              <CreateStoryForm onCreated={(id) => navigate(`/studio/${id}`)} />
            </CardContent>
          </Card>
        )}
      </div>
    </>
  );
}
