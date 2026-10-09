import { describe, expect, it, vi } from "vitest";

import { createApiClient, normalizeApiPath } from "./api-client";

describe("api client", () => {
  it("normalizes legacy API paths once", () => {
    expect(normalizeApiPath("/api/games")).toBe("/api/v1/games");
    expect(normalizeApiPath("/api/v1/games")).toBe("/api/v1/games");
  });

  it("adds cookie credentials and CSRF to writes", async () => {
    const fetchImpl = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => (
      new Response(JSON.stringify({ ok: true }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      })
    ));
    const client = createApiClient({
      fetchImpl: fetchImpl as typeof fetch,
      getCsrfToken: () => "csrf-value",
    });

    await client.request("/api/auth/logout", { method: "POST" });

    expect(fetchImpl).toHaveBeenCalledOnce();
    const [path, options] = fetchImpl.mock.calls[0];
    if (!options) throw new Error("fetch options are required");
    expect(path).toBe("/api/v1/auth/logout");
    expect(options.credentials).toBe("same-origin");
    expect(new Headers(options.headers).get("X-CSRF-Token")).toBe("csrf-value");
  });

  it("surfaces structured errors and unauthorized state", async () => {
    const onUnauthorized = vi.fn();
    const client = createApiClient({
      fetchImpl: async () => new Response(JSON.stringify({
        code: "AUTH_REQUIRED",
        message: "请先登录",
        request_id: "request-123",
        details: {},
      }), {
        status: 401,
        headers: { "Content-Type": "application/json" },
      }),
      getCsrfToken: () => "",
      onUnauthorized,
    });

    await expect(client.request("/api/games")).rejects.toMatchObject({
      status: 401,
      code: "AUTH_REQUIRED",
      requestId: "request-123",
      message: "请先登录（请求 request-123）",
    });
    expect(onUnauthorized).toHaveBeenCalledWith("/api/v1/games");
  });
});
