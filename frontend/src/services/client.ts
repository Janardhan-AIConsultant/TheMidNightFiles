import axios from "axios";
import type { AxiosRequestConfig } from "axios";
import type { z } from "zod";
import { apiErrorBody } from "@/schemas";

export const API_BASE_URL: string = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api/v1";

export class ApiError extends Error {
  constructor(
    public code: string,
    message: string,
    public details?: unknown,
    public status?: number,
  ) {
    super(message);
    this.name = "ApiError";
  }

  /** Human-readable reasons supplied by the backend (e.g. approval eligibility failures). */
  get reasons(): string[] {
    const d = this.details as { reasons?: unknown } | unknown[] | null | undefined;
    const list = Array.isArray(d) ? d : d && typeof d === "object" && Array.isArray(d.reasons) ? d.reasons : [];
    return list.map((r) => (typeof r === "string" ? r : JSON.stringify(r)));
  }
}

export const http = axios.create({ baseURL: API_BASE_URL, timeout: 20_000, headers: { Accept: "application/json" } });

export function toApiError(err: unknown): ApiError {
  if (err instanceof ApiError) return err;
  if (axios.isAxiosError(err)) {
    const parsed = apiErrorBody.safeParse(err.response?.data);
    if (parsed.success) {
      const { code, message, details } = parsed.data.error;
      return new ApiError(code, message, details, err.response?.status);
    }
    if (err.code === "ECONNABORTED") return new ApiError("timeout", "The request timed out.");
    if (!err.response) return new ApiError("network_error", "Cannot reach the API. Is the backend running?");
    return new ApiError("http_error", `Request failed (${err.response.status}).`, err.response.data, err.response.status);
  }
  return new ApiError("unknown", err instanceof Error ? err.message : "Unexpected error");
}

/** Single entry point: performs the request, normalises errors, validates the response with Zod. */
export async function request<S extends z.ZodTypeAny>(schema: S, config: AxiosRequestConfig): Promise<z.output<S>> {
  let data: unknown;
  try {
    data = (await http.request(config)).data;
  } catch (err) {
    throw toApiError(err);
  }
  const parsed = schema.safeParse(data);
  if (!parsed.success) {
    throw new ApiError("invalid_response", `Unexpected response from ${config.url}`, parsed.error.issues);
  }
  return parsed.data;
}
