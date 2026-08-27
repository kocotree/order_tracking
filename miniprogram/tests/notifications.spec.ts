import { describe, expect, it } from "vitest";

import { buildSubscriptionRequest, mapSubscriptionResults, notificationTarget } from "../modules/notifications";

describe("mini-program notification subscription seams", () => {
  it("deduplicates business categories sharing one actual template and never requests over three IDs", () => {
    expect(buildSubscriptionRequest("factory", {
      factory_order: "template-order",
      factory_repair: "template-repair",
    })).toEqual({ templateIds: ["template-order", "template-repair"], missingKeys: [] });
    expect(buildSubscriptionRequest("factory", { factory_order:"template-order" })).toEqual({ templateIds:["template-order"], missingKeys:["factory_repair"] });
    expect(() => buildSubscriptionRequest("factory", {
      factory_order: "one",
      factory_repair: "two",
      extra_one: "three",
      extra_two: "four",
    } as never)).not.toThrow();
  });

  it("maps one actual result back to every compatible logical business category", () => {
    expect(mapSubscriptionResults("factory", {
      factory_order: "shared-order-template",
      factory_repair: "repair-template",
    }, {
      "shared-order-template": "accept",
      "repair-template": "reject",
    })).toEqual({ factory_order: "accepted", factory_repair: "rejected" });
  });

  it("adds notification context without trusting a server target outside approved pages", () => {
    expect(notificationTarget("/pages/factory-task-detail/factory-task-detail?orderId=o-1", "factory_task", "o-1", 9, "unread")).toBe("/pages/factory-task-detail/factory-task-detail?orderId=o-1&notificationId=9&notificationStatus=unread");
    expect(notificationTarget("/shipments/s-1", "shipment", "s-1", 9, "all")).toBe("/pages/admin-shipment-detail/admin-shipment-detail?shipmentId=s-1&notificationId=9&notificationStatus=all");
    expect(notificationTarget("/pages/unknown/unknown", "unknown", "x", 9, "all")).toBeNull();
  });
});
