import { beforeEach, describe, expect, it, vi } from "vitest";

import { orderApi } from "@/api/client";

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
});
