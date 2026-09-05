import { afterEach, beforeEach, expect, it, vi } from "vitest";

let page: { goBack(): void };
let stack: string[];
let role = "admin";

beforeEach(() => {
  vi.resetModules();
  role = "admin";
  stack = ["detail"];
  vi.stubGlobal("Page", (definition: typeof page) => { page = definition; });
  vi.stubGlobal("getCurrentPages", () => stack.map(route => ({ route })));
  vi.stubGlobal("wx", {
    getStorageSync: () => "token",
    getAccountInfoSync: () => ({ miniProgram: { envVersion: "develop" } }),
    navigateBack: vi.fn((options?: WechatMiniprogram.NavigateBackOption) => {
      if (stack.length > 1) stack.pop();
      else options?.fail?.({ errMsg: "no previous page" });
    }),
    reLaunch: vi.fn((options: WechatMiniprogram.ReLaunchOption) => { stack = [options.url]; }),
    showToast: vi.fn(),
    request: vi.fn((options: WechatMiniprogram.RequestOption) => {
      options.success?.({ data: { role, isEnabled: true }, statusCode: 200, header: {}, cookies: [], errMsg: "ok" } as unknown as Parameters<NonNullable<typeof options.success>>[0]);
    }),
  });
});
afterEach(() => { vi.unstubAllGlobals(); });

it.each(["admin", "factory"] as const)("returns the %s notification single-page entry to its shipment list", async (currentRole) => {
  role = currentRole;
  if (role === "admin") await import("../pages/admin-shipment-detail/admin-shipment-detail");
  else await import("../pages/factory-shipment-detail/factory-shipment-detail");
  page.goBack();
  await vi.waitFor(() => expect(stack).toEqual([`/pages/${currentRole}-shipments/${currentRole}-shipments`]));
});

it.each(["admin", "factory"] as const)("preserves the previous page for a normal %s entry", async (currentRole) => {
  stack = ["notifications?filter=unread", "detail"];
  if (currentRole === "admin") await import("../pages/admin-shipment-detail/admin-shipment-detail");
  else await import("../pages/factory-shipment-detail/factory-shipment-detail");
  page.goBack();
  expect(stack).toEqual(["notifications?filter=unread"]);
  expect(wx.request).not.toHaveBeenCalled();
});
