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

const loadNotificationPage = {
  "admin-order-detail": () => import("../pages/admin-order-detail/admin-order-detail"),
  "factory-task-detail": () => import("../pages/factory-task-detail/factory-task-detail"),
  "admin-repair-detail": () => import("../pages/admin-repair-detail/admin-repair-detail"),
  "factory-repair-detail": () => import("../pages/factory-repair-detail/factory-repair-detail"),
};

const notificationPages = [
  ["admin", "admin-order-detail", "/pages/admin-orders/admin-orders"],
  ["factory", "factory-task-detail", "/pages/factory-tasks/factory-tasks"],
  ["admin", "admin-repair-detail", "/pages/admin-shipments/admin-shipments"],
  ["factory", "factory-repair-detail", "/pages/factory-tasks/factory-tasks"],
] as const;

it.each(notificationPages)("returns a single-page %s %s notification to its role entry", async (currentRole, name, destination) => {
  role = currentRole;
  await loadNotificationPage[name]();
  page.goBack();
  await vi.waitFor(() => expect(stack).toEqual([destination]));
});

it.each(notificationPages)("preserves the previous notification page for %s %s", async (_role, name) => {
  stack = ["notifications?filter=unread", "detail"];
  await loadNotificationPage[name]();
  page.goBack();
  expect(stack).toEqual(["notifications?filter=unread"]);
  expect(wx.request).not.toHaveBeenCalled();
});

it.each(notificationPages)("handles navigateBack failure for %s %s", async (currentRole, name, destination) => {
  role = currentRole;
  stack = ["notifications", "detail"];
  vi.mocked(wx.navigateBack).mockImplementation(options => {
    options?.fail?.({ errMsg: "navigateBack:fail" });
  });
  await loadNotificationPage[name]();
  page.goBack();
  await vi.waitFor(() => expect(stack).toEqual([destination]));
});
