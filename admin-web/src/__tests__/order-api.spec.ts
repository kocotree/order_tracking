import { beforeEach, describe, expect, it, vi } from "vitest";

import { identityApi, orderApi } from "@/api/client";

describe("orderApi", () => {
  beforeEach(() => {
    document.cookie = "ot_csrf=csrf-value";
    vi.spyOn(globalThis.crypto, "randomUUID").mockReturnValue(
      "00000000-0000-4000-8000-000000000001",
    );
  });

  it("sends server-owned query filters and idempotency headers", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ items: [], total: 0, page: 1, pageSize: 20 }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ orderId: "order-1" }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );

    await orderApi.list({ status: "已逾期", includeDrafts: true, trackers: ["松子"] });
    await orderApi.publish("order-1", 3);

    expect(String(fetchMock.mock.calls[0]?.[0])).toContain("status=%E5%B7%B2%E9%80%BE%E6%9C%9F");
    expect(String(fetchMock.mock.calls[0]?.[0])).toContain("includeDrafts=true");
    const publish = fetchMock.mock.calls[1]?.[1];
    expect(new Headers(publish?.headers).get("Idempotency-Key")).toBe(
      "00000000-0000-4000-8000-000000000001",
    );
    expect(new Headers(publish?.headers).get("X-CSRF-Token")).toBe("csrf-value");
  });

  it("shares one refresh when concurrent requests receive 401, then retries both", async () => {
    let meCalls = 0;
    let refreshCalls = 0;
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.endsWith("/v1/auth/refresh")) {
        refreshCalls += 1;
        return new Response(null, { status: 204 });
      }
      if (url.endsWith("/v1/me")) {
        meCalls += 1;
        if (meCalls <= 2) {
          return new Response(JSON.stringify({ code: "session_invalid" }), {
            status: 401,
            headers: { "Content-Type": "application/json" },
          });
        }
        return new Response(
          JSON.stringify({ userId: `user-${meCalls}`, role: "admin" }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        );
      }
      throw new Error(`unexpected request: ${url}`);
    });

    const users = await Promise.all([identityApi.getMe(), identityApi.getMe()]);

    expect(refreshCalls).toBe(1);
    expect(meCalls).toBe(4);
    expect(users).toHaveLength(2);
  });
});
