import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";

import { notificationApi, orderApi, type Order } from "@/api/client";
import HomePage from "@/pages/HomePage.vue";

function order(overrides: Partial<Order> = {}): Order {
  return {
    orderId: "order-1",
    orderNo: "090#",
    source: "manual",
    orderDate: "2026-08-20",
    tracker: "橄榄",
    contractShipDate: "2026-08-25",
    lifecycle: "PUBLISHED",
    displayStatus: "未完成",
    version: 1,
    totalQuantity: 100,
    shippedQuantity: 20,
    pendingQuantity: 80,
    overQuantity: 0,
    shortQuantity: 0,
    progressPercent: 20,
    lines: [
      {
        orderLineId: 1,
        variantId: "variant-1",
        skuId: "SKU-1",
        productName: "晴雨机能风衣",
        propertiesValue: "蓝色 / 120",
        category: "童装春夏",
        imageObjectKey: null,
        orderQuantity: 100,
        shippedQuantity: 20,
        pendingQuantity: 80,
        overQuantity: 0,
        shortQuantity: 0,
        progressPercent: 20,
        assignments: [],
      },
    ],
    factoryProgress: [{ factoryId: "factory-1", factoryName: "启宏", orderQuantity: 100, shippedQuantity: 20, pendingQuantity: 80, overQuantity: 0, shortQuantity: 0, progressPercent: 20 }],
    validationIssues: [],
    createdAt: "2026-08-20T08:00:00Z",
    updatedAt: "2026-08-20T08:00:00Z",
    requestId: "request-1",
    ...overrides,
  };
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("order dashboard prototype alignment", () => {
  it("maps product categories, excludes specifications from search, and sorts table columns", async () => {
    const mixedOrder = order({
      orderId: "order-2",
      orderNo: "078#",
      lines: [
        order().lines[0],
        { ...order().lines[0], orderLineId: 2, variantId: "variant-2", skuId: "SKU-2", productName: "轻量防晒帽", category: "童帽秋冬" },
      ],
    });
    vi.spyOn(orderApi, "dashboard").mockResolvedValue({
      overdueOrders: 1,
      pendingImportOrders: 0,
      todayShipments: 0,
      recentOrders: [order(), mixedOrder],
      requestId: "request-dashboard",
    });
    vi.spyOn(notificationApi, "list").mockResolvedValue({ items: [], total: 0, page: 1, pageSize: 3, requestId: "request-notifications" });

    const wrapper = mount(HomePage, {
      global: {
        stubs: {
          AdminShell: { template: "<div><slot /></div>" },
          RouterLink: { props: ["to"], template: "<a><slot /></a>" },
        },
      },
    });
    await flushPromises();

    expect(wrapper.findAll('[data-category="服装"]')).toHaveLength(2);
    expect(wrapper.findAll('[data-category="帽子"]')).toHaveLength(1);

    await wrapper.get('.dashboard-search-field input').setValue("蓝色");
    await wrapper.get('.dashboard-search-form').trigger("submit");
    expect(wrapper.text()).toContain("找到 0 个订单");

    await wrapper.get('.dashboard-search-clear').trigger("click");
    const orderNumberHeader = wrapper.findAll('.data-grid-sort-button').find((item) => item.text().includes("订单编号"));
    await orderNumberHeader?.trigger("click");
    expect(wrapper.findAll("tbody tr")[0].text()).toContain("078#");
    await orderNumberHeader?.trigger("click");
    expect(wrapper.findAll("tbody tr")[0].text()).toContain("090#");
  });
});
