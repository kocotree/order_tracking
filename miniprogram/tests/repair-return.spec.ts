import { describe, expect, it } from "vitest";

import { buildReturnEntries, prepareReturnSubmission } from "../modules/repair-return";

const specs = [
  { variantId: "variant-1", productName: "云朵软壳冲锋衣", propertiesValue: "松石绿/110", warehouseReturnQuantity: 12, repairedQuantity: 3, scrappedQuantity: 1, returnedQuantity: 4, pendingQuantity: 8 },
  { variantId: "variant-2", productName: "云朵软壳冲锋衣", propertiesValue: "米白/110", warehouseReturnQuantity: 5, repairedQuantity: 5, scrappedQuantity: 0, returnedQuantity: 5, pendingQuantity: 0 },
];

describe("factory repair return form", () => {
  it("only creates editable entries for specs that still have pending quantity", () => {
    expect(buildReturnEntries(specs)).toEqual([expect.objectContaining({ variantId: "variant-1", selected: false, repaired: "", scrapped: "" })]);
  });

  it("builds a strict integer submission for selected specs", () => {
    const entries = buildReturnEntries(specs);
    entries[0].selected = true;
    entries[0].repaired = "6";
    entries[0].scrapped = "2";

    expect(prepareReturnSubmission(entries)).toEqual({
      ok: true,
      lines: [{ variantId: "variant-1", repairedQuantity: 6, scrappedQuantity: 2 }],
    });
  });

  it("rejects decimals, zero totals, and quantities above the current pending amount", () => {
    const entries = buildReturnEntries(specs);
    entries[0].selected = true;
    entries[0].repaired = "1.5";
    expect(prepareReturnSubmission(entries)).toEqual({ ok: false, message: "返修数量和报废数量只能填写非负整数" });
    entries[0].repaired = "0";
    entries[0].scrapped = "0";
    expect(prepareReturnSubmission(entries)).toEqual({ ok: false, message: "松石绿/110的返修数量和报废数量不能同时为0" });
    entries[0].repaired = "9";
    expect(prepareReturnSubmission(entries)).toEqual({ ok: false, message: "松石绿/110本次返回数量不能超过待返回数量" });
  });
});
