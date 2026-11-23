import { useState } from "react";
import { Button, Card, CardContent, CardHeader, CardTitle, Input, Label } from "@/components/ui/primitives";
import { PageHeader, QueryBoundary, StatusBadge } from "@/components/common/common";
import { useSaveSettings, useSettings } from "@/hooks/queries";
import { toApiError } from "@/services/client";
import { humanize } from "@/lib/utils";
import type { Settings } from "@/schemas";

/** Mirrors backend routes_system.EDITABLE; the backend validates every value again. */
export const FIELD_TYPES: Record<string, { type: "int" | "bool" | "str"; min?: number; max?: number }> = {
  "scheduler.calendar_hour": { type: "int", min: 0, max: 23 },
  "scheduler.calendar_minute": { type: "int", min: 0, max: 59 },
  "scheduler.publishing_interval_seconds": { type: "int", min: 10, max: 86400 },
  "scheduler.enabled": { type: "bool" },
  "ui.theme": { type: "str" },
  "publishing.default_platform": { type: "str" },
};

type FormState = Record<string, string | boolean>;

const initial = (keys: string[], operator: Record<string, unknown>): FormState =>
  Object.fromEntries(keys.map((k) => [k, FIELD_TYPES[k]?.type === "bool" ? operator[k] === true : operator[k] == null ? "" : String(operator[k])]));

/** Build the PUT /settings `values` map from changed fields only, coercing to the backend's types. */
export function buildValues(form: FormState, operator: Record<string, unknown>): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(form)) {
    const spec = FIELD_TYPES[k];
    const before = operator[k];
    if (spec?.type === "bool") {
      if (v !== (before === true)) out[k] = v;
    } else if (spec?.type === "int") {
      if (v === "" || String(before ?? "") === v) continue;
      out[k] = Number(v);
    } else if (v !== "" && String(before ?? "") !== v) {
      out[k] = v;
    }
  }
  return out;
}

const show = (v: unknown) => (typeof v === "object" && v !== null ? JSON.stringify(v) : String(v));

function SettingsForm({ data }: { data: Settings }) {
  const save = useSaveSettings();
  const [form, setForm] = useState<FormState>(() => initial(data.editable_keys, data.operator));
  const [error, setError] = useState<ReturnType<typeof toApiError> | null>(null);
  const values = buildValues(form, data.operator);
  const { secrets, ...config } = data.config as { secrets?: Record<string, { configured: boolean; value?: string | null }> } & Record<string, unknown>;

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle>Operator settings</CardTitle>
        </CardHeader>
        <CardContent>
          <form
            aria-label="Settings"
            className="space-y-4"
            onSubmit={(e) => {
              e.preventDefault();
              setError(null);
              save.mutate(values, { onError: (err) => setError(toApiError(err)) });
            }}
          >
            <div className="grid gap-4 md:grid-cols-2">
              {data.editable_keys.map((key) => {
                const spec = FIELD_TYPES[key];
                const id = `s-${key}`;
                if (spec?.type === "bool") {
                  return (
                    <label key={key} className="flex items-center gap-2 text-sm">
                      <input type="checkbox" className="accent-[hsl(var(--primary))]" checked={form[key] === true} onChange={(e) => setForm({ ...form, [key]: e.target.checked })} />
                      {humanize(key.split(".").join(" "))}
                    </label>
                  );
                }
                return (
                  <div key={key}>
                    <Label htmlFor={id}>{humanize(key.split(".").join(" "))}</Label>
                    <Input
                      id={id}
                      type={spec?.type === "int" ? "number" : "text"}
                      min={spec?.min}
                      max={spec?.max}
                      autoComplete="off"
                      value={String(form[key] ?? "")}
                      onChange={(e) => setForm({ ...form, [key]: e.target.value })}
                    />
                  </div>
                );
              })}
            </div>
            {error && (
              <div role="alert" className="rounded border border-primary/40 bg-primary/10 p-3 text-sm">
                <p className="font-medium text-primary">{error.message}</p>
                {Array.isArray(error.details) && (
                  <ul className="mt-1 list-disc pl-5 text-muted-foreground">
                    {(error.details as { key?: string; message?: string }[]).map((d, i) => (
                      <li key={i}>
                        {d.key}: {d.message}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}
            <Button type="submit" disabled={Object.keys(values).length === 0 || save.isPending}>
              {save.isPending ? "Saving…" : "Save settings"}
            </Button>
          </form>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Environment configuration (read-only)</CardTitle>
        </CardHeader>
        <CardContent>
          {data.read_only_note && <p className="mb-3 text-xs text-muted-foreground">{data.read_only_note}</p>}
          <dl className="grid gap-x-4 gap-y-1 text-sm sm:grid-cols-[14rem_1fr]">
            {Object.entries(config).map(([k, v]) => (
              <div key={k} className="contents">
                <dt className="text-muted-foreground">{humanize(k)}</dt>
                <dd className="break-words">{show(v)}</dd>
              </div>
            ))}
          </dl>
        </CardContent>
      </Card>

      {secrets && (
        <Card>
          <CardHeader>
            <CardTitle>Secrets</CardTitle>
          </CardHeader>
          <CardContent>
            <ul className="space-y-1 text-sm">
              {Object.entries(secrets).map(([k, s]) => (
                <li key={k} className="flex items-center gap-3">
                  <span className="w-48 text-muted-foreground">{humanize(k)}</span>
                  <StatusBadge status={s.configured ? "configured" : "not configured"} />
                  {s.value && <code className="text-xs">{s.value}</code>}
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

export default function SettingsPage() {
  const q = useSettings();
  return (
    <>
      <PageHeader title="Settings" description="Operator settings are editable; infrastructure and secrets come from the environment and are masked." />
      <QueryBoundary query={q}>{(d) => <SettingsForm data={d} />}</QueryBoundary>
    </>
  );
}
