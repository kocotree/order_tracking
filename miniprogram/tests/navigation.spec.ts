import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { adminNavigationItems, returnFromShipmentDetail } from "../modules/navigation";

describe("mini-program primary navigation", () => {
  it("shows the same order, shipment, and profile destinations for administrators", () => {
    expect(adminNavigationItems()).toEqual([
      {
        key: "primary",
        label: "订单",
        path: "/pages/admin-orders/admin-orders",
        icon: "/assets/icons/admin-orders.svg",
        activeIcon: "/assets/icons/admin-orders-active.svg",
      },
      {
        key: "shipments",
        label: "发货",
        path: "/pages/admin-shipments/admin-shipments",
        icon: "/assets/icons/factory-shipments.svg",
        activeIcon: "/assets/icons/factory-shipments-active.svg",
      },
      {
        key: "profile",
        label: "我的",
        path: "/pages/profile/profile",
        icon: "/assets/icons/admin-profile.svg",
        activeIcon: "/assets/icons/admin-profile-active.svg",
      },
    ]);
  });
});

describe("shipment detail return fallback", () => {
  let stack: string[];
  let role: string | null;
  let enabled: boolean;
  let status: number;
  let refreshed: boolean;
  let refreshFails: boolean;

  beforeEach(() => {
    stack = ["detail"];
    role = "factory";
    enabled = true;
    status = 200;
    refreshed = false;
    refreshFails = false;
    vi.stubGlobal("getCurrentPages", () => stack.map(route => ({ route })));
    vi.stubGlobal("wx", {
      getStorageSync: (key: string) => key === "identity.user" ? { role: "admin" } : "saved-token",
      setStorageSync: vi.fn(),
      getAccountInfoSync: () => ({ miniProgram: { envVersion: "develop" } }),
      navigateBack: vi.fn((options: WechatMiniprogram.NavigateBackOption) => {
        options.fail?.({ errMsg: "navigation failed" });
      }),
      reLaunch: vi.fn((options: WechatMiniprogram.ReLaunchOption) => { stack = [options.url]; }),
      request: vi.fn((options: WechatMiniprogram.RequestOption) => {
        if (options.url.endsWith("/mini/auth/refresh")) {
          refreshed = !refreshFails;
          options.success?.({ data: { accessToken: "renewed", refreshToken: "renewed-refresh" }, statusCode: refreshFails ? 401 : 200, header: {}, cookies: [], errMsg: "ok" } as unknown as Parameters<NonNullable<typeof options.success>>[0]);
        } else {
          options.success?.({ data: { role, isEnabled: enabled }, statusCode: refreshed ? 200 : status, header: {}, cookies: [], errMsg: "ok" } as unknown as Parameters<NonNullable<typeof options.success>>[0]);
        }
      }),
    });
  });
  afterEach(() => { vi.unstubAllGlobals(); });

  it("uses the current server role instead of a stale stored administrator role", async () => {
    returnFromShipmentDetail();
    await vi.waitFor(() => expect(stack).toEqual(["/pages/factory-shipments/factory-shipments"]));
  });

  it("falls back when navigateBack fails even with a previous page", async () => {
    stack = ["list", "detail"];
    returnFromShipmentDetail();
    await vi.waitFor(() => expect(stack).toEqual(["/pages/factory-shipments/factory-shipments"]));
  });

  it.each(["disabled", "unassigned", "forbidden", "expired"])("sends an %s identity to authentication without a return loop", async (scenario) => {
    if (scenario === "disabled") enabled = false;
    if (scenario === "unassigned") role = null;
    if (scenario === "forbidden") status = 403;
    if (scenario === "expired") { status = 401; refreshFails = true; }
    returnFromShipmentDetail();
    await vi.waitFor(() => expect(stack).toEqual(["/pages/auth/auth"]));
    expect(wx.reLaunch).toHaveBeenCalledTimes(1);
  });

  it("restores an expired access token through the existing refresh flow before choosing a destination", async () => {
    status = 401;
    returnFromShipmentDetail();
    await vi.waitFor(() => expect(stack).toEqual(["/pages/factory-shipments/factory-shipments"]));
    expect(refreshed).toBe(true);
  });
});
