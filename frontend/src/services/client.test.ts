import { afterEach, describe, expect, it } from "vitest";
import type { AxiosAdapter, InternalAxiosRequestConfig } from "axios";
import { AxiosError } from "axios";
import { z } from "zod";
import { ApiError, http, request } from "./client";
import { pageOf } from "@/schemas";

const original = http.defaults.adapter;
afterEach(() => {
  http.defaults.adapter = original;
});

const respond = (status: number, data: unknown): AxiosAdapter => async (config: InternalAxiosRequestConfig) => {
  const response = { data, status, statusText: "", headers: {}, config };
  if (status >= 400) throw new AxiosError("fail", "ERR_BAD_REQUEST", config, null, response);
  return response;
};

describe("api client", () => {
  it("validates and returns data", async () => {
    http.defaults.adapter = respond(200, { a: 1 });
    await expect(request(z.object({ a: z.number() }), { url: "/x" })).resolves.toEqual({ a: 1 });
  });

  it("normalises backend error envelope including reasons", async () => {
    http.defaults.adapter = respond(409, { error: { code: "approval_error", message: "Not eligible", details: { reasons: ["Safety not PASSED"] } } });
    const err = await request(z.any(), { url: "/approvals", method: "POST" }).catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.code).toBe("approval_error");
    expect(err.reasons).toEqual(["Safety not PASSED"]);
  });

  it("rejects responses that do not match the schema", async () => {
    http.defaults.adapter = respond(200, { a: "nope" });
    const err = await request(z.object({ a: z.number() }), { url: "/x" }).catch((e) => e);
    expect(err.code).toBe("invalid_response");
  });

  it("normalises bare arrays and paginated envelopes", async () => {
    const schema = pageOf(z.object({ n: z.number() }));
    http.defaults.adapter = respond(200, [{ n: 1 }]);
    expect((await request(schema, { url: "/l" })).total).toBe(1);
    http.defaults.adapter = respond(200, { items: [{ n: 1 }, { n: 2 }], total: 40, page: 2, page_size: 2 });
    expect(await request(schema, { url: "/l" })).toMatchObject({ total: 40, page: 2 });
  });
});
