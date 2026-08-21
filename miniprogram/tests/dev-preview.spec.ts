import { describe, expect, it } from "vitest";

import { canUseDevPreview } from "../modules/dev-preview";

describe("mini-program development preview", () => {
  it("only enables preview for an explicit request inside WeChat DevTools", () => {
    expect(canUseDevPreview("1", "devtools")).toBe(true);
    expect(canUseDevPreview(undefined, "devtools")).toBe(false);
    expect(canUseDevPreview("1", "ios")).toBe(false);
    expect(canUseDevPreview("1", "android")).toBe(false);
  });
});
