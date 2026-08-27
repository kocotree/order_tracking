import { describe, expect, it } from "vitest";

import { canUseDevPreview, PREVIEW_ADMIN_REPAIRS, PREVIEW_REPAIRS, previewAdminRepair, previewRepair } from "../modules/dev-preview";

describe("mini-program development preview", () => {
  it("only enables preview for an explicit request inside WeChat DevTools", () => {
    expect(canUseDevPreview("1", "devtools")).toBe(true);
    expect(canUseDevPreview(undefined, "devtools")).toBe(false);
    expect(canUseDevPreview("1", "ios")).toBe(false);
    expect(canUseDevPreview("1", "android")).toBe(false);
  });

  it("provides coherent repair list and detail preview data", () => {
    expect(PREVIEW_REPAIRS).toHaveLength(2);
    expect(PREVIEW_REPAIRS.map((repair) => repair.repairNo)).toEqual([
      "FX20260812-001",
      "FX20260810-002",
    ]);
    expect(previewRepair("preview-repair-2")?.returnedQuantity).toBe(420);
    expect(previewRepair("missing-repair")).toBeUndefined();
  });

  it("provides administrator repair progress and return-record preview data", () => {
    expect(PREVIEW_ADMIN_REPAIRS).toHaveLength(4);
    expect(new Set(PREVIEW_ADMIN_REPAIRS.map((repair) => repair.factoryId)).size).toBe(4);
    expect(previewAdminRepair("preview-admin-repair-1")?.returnBatches?.[0]?.lines).toHaveLength(2);
    expect(previewAdminRepair("missing-repair")).toBeUndefined();
  });
});
