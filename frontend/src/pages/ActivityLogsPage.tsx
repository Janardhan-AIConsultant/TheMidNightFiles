import { useState } from "react";
import { Card, Label, Select, Table, Td, Th } from "@/components/ui/primitives";
import { PageHeader, QueryBoundary, StatusBadge } from "@/components/common/common";
import { useLogs } from "@/hooks/queries";
import { fmtDate } from "@/lib/utils";

const CHANNELS = ["app", "agent", "publishing", "scheduler", "error"];
const LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"];

export default function ActivityLogsPage() {
  const [channel, setChannel] = useState("app");
  const [level, setLevel] = useState("");
  const [limit, setLimit] = useState(100);
  const q = useLogs({ channel, level, limit });

  return (
    <>
      <PageHeader title="Activity Logs" description="Operational logs served by the API (redacted server-side)." />
      <Card>
        <div className="grid gap-3 border-b border-border p-4 sm:grid-cols-3">
          <div>
            <Label htmlFor="log-channel">Channel</Label>
            <Select id="log-channel" value={channel} onChange={(e) => setChannel(e.target.value)}>
              {CHANNELS.map((c) => (
                <option key={c}>{c}</option>
              ))}
            </Select>
          </div>
          <div>
            <Label htmlFor="log-level">Minimum level</Label>
            <Select id="log-level" value={level} onChange={(e) => setLevel(e.target.value)}>
              <option value="">All</option>
              {LEVELS.map((l) => (
                <option key={l}>{l}</option>
              ))}
            </Select>
          </div>
          <div>
            <Label htmlFor="log-limit">Rows</Label>
            <Select id="log-limit" value={limit} onChange={(e) => setLimit(Number(e.target.value))}>
              {[50, 100, 250, 500].map((n) => (
                <option key={n}>{n}</option>
              ))}
            </Select>
          </div>
        </div>
        <QueryBoundary query={q} isEmpty={(d) => d.items.length === 0} empty={{ title: "No log entries match" }}>
          {(d) => (
            <Table>
              <thead>
                <tr>
                  <Th>Time</Th>
                  <Th>Level</Th>
                  <Th>Logger</Th>
                  <Th>Message</Th>
                </tr>
              </thead>
              <tbody>
                {d.items.map((l, i) => (
                  <tr key={i}>
                    <Td className="whitespace-nowrap">{fmtDate(l.timestamp)}</Td>
                    <Td>
                      <StatusBadge status={l.severity} />
                    </Td>
                    <Td>{l.logger ?? "—"}</Td>
                    <Td className="break-words font-mono text-xs">{l.message ?? JSON.stringify(l)}</Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )}
        </QueryBoundary>
      </Card>
    </>
  );
}
