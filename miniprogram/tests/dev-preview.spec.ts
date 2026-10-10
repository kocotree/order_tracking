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
    expect(PREVIEW_REPAIRS.length).toBeGreaterThan(0);
    for (const repair of PREVIEW_REPAIRS) {
      expect(previewRepair(repair.repairId)).toMatchObject(repair);
    }
    expect(previewRepair("missing-repair")).toBeUndefined();
  });

  it("provides administrator repair progress and return-record preview data", () => {
    expect(PREVIEW_ADMIN_REPAIRS.length).toBeGreaterThan(0);
    for (const repair of PREVIEW_ADMIN_REPAIRS) {
      expect(previewAdminRepair(repair.repairId)).toMatchObject(repair);
    }
    expect(previewAdminRepair("missing-repair")).toBeUndefined();
  });
});
