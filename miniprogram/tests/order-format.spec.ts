import { describe, expect, it } from "vitest";

import type { Order } from "../api/orders";
import { orderProductSummary, statusTone } from "../modules/orders/format";

describe("order presentation", () => {
  it("deduplicates product names and uses the shared status tone", () => {
    const order = {
      lines: [
        { productName: "晴雨两用风衣" },
        { productName: "晴雨两用风衣" },
        { productName: "儿童遮阳帽" },
      ],
    } as Order;
    expect(orderProductSummary(order)).toBe("晴雨两用风衣、儿童遮阳帽");
    expect(statusTone("已逾期")).toBe("overdue");
    expect(statusTone("已完成")).toBe("completed");
    expect(statusTone("未完成")).toBe("pending");
  });
});
