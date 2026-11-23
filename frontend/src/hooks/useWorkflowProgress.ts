import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/services/api";
import { API_BASE_URL } from "@/services/client";
import { keys } from "./queries";

/** Mirrors backend graph_state.TERMINAL. `awaiting_human` and `interrupted` are NOT terminal. */
export const TERMINAL = ["completed", "failed", "terminated", "stale"];

/** Event names the backend emits on /workflows/{id}/events (SSE `event:` field). */
export const WORKFLOW_EVENTS = ["snapshot", "workflow_started", "workflow_status", "workflow_resumed", "stage_started", "stage_failed", "end"];

/**
 * Real progress only: the workflow document comes from GET /workflows/{id}.
 * While it is non-terminal we subscribe to the SSE stream (/workflows/{id}/events). The stream uses
 * named events and carries deltas, not full documents, so every event simply refetches the workflow
 * document; if SSE is unavailable or errors, controlled polling takes over.
 */
export function useWorkflowProgress(workflowId: string | undefined) {
  const qc = useQueryClient();
  const [sseActive, setSseActive] = useState(false);

  const query = useQuery({
    queryKey: keys.workflow(workflowId ?? ""),
    queryFn: () => api.workflow(workflowId!),
    enabled: !!workflowId,
    refetchInterval: (q) => {
      const status = q.state.data?.status?.toLowerCase();
      if (status && TERMINAL.includes(status)) return false;
      return sseActive ? false : 3000;
    },
  });

  const terminal = query.data ? TERMINAL.includes(query.data.status.toLowerCase()) : false;

  useEffect(() => {
    if (!workflowId || terminal || typeof EventSource === "undefined") return;
    const source = new EventSource(`${API_BASE_URL}/workflows/${workflowId}/events`);
    const refresh = () => void qc.invalidateQueries({ queryKey: keys.workflow(workflowId) });
    source.onopen = () => setSseActive(true);
    source.onmessage = refresh;
    for (const name of WORKFLOW_EVENTS) source.addEventListener(name, refresh);
    source.onerror = () => {
      setSseActive(false);
      source.close();
    };
    return () => {
      source.close();
      setSseActive(false);
    };
  }, [workflowId, terminal, qc]);

  return { ...query, terminal, live: sseActive };
}
