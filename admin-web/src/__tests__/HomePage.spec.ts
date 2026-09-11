import { createPinia } from "pinia";
import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";

import { createMemoryHistory, createRouter } from "vue-router";
import { notificationApi, orderApi, type Order } from "@/api/client";
import HomePage from "@/pages/HomePage.vue";

function order(overrides: Partial<Order> = {}): Order {
  return {
    detailMode: false, details: [], orderId: "order-1",
    orderNo: "090#",
    source: "manual",
    orderDate: "2026-08-20",
    tracker: "橄榄",
    contractShipDates: ["2026-08-25"], contractShipDate: "2026-08-25",
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
    vi.spyOn(notificationApi, "unreadCount").mockResolvedValue({ count: 1, requestId: "test" });
    vi.spyOn(notificationApi, "list").mockResolvedValue({ items: [], total: 0, page: 1, pageSize: 3, requestId: "request-notifications" });

    const wrapper = mount(HomePage, {
      global: { plugins: [createPinia()],
        stubs: {
          AdminShell: { template: "<div><slot /></div>" },
          RouterLink: { props: ["to"], template: "<a><slot /></a>" },
        },
      },
    });
    await flushPromises();

    expect(wrapper.findAll(".dashboard-order-link").map((link) => link.attributes("title"))).toEqual(["090#", "078#"]);
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

it("links statistics to Shanghai today and overdue filters, and requests unread summaries", async () => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-09-05T18:00:00Z"));
  vi.spyOn(orderApi, "dashboard").mockResolvedValue({ recentOrders: [], overdueOrders: 2, todayShipments: 1, pendingImportOrders: 0 } as never);
  vi.spyOn(notificationApi, "list").mockResolvedValue({ items: [{
    notificationId: 1, title: "希望工厂提交发货", summary: "希望工厂发货：童帽等，总计560件",
    targetPath: "/shipments/test", readAt: null, createdAt: "2026-09-05T10:00:00Z",
  }], total: 1 } as never);
  vi.spyOn(notificationApi, "unreadCount").mockResolvedValue({ count: 0 } as never);
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: "/:pathMatch(.*)*", component: { template: "<div/>" } }] });
  await router.push("/");
  const wrapper = mount(HomePage, { global: { plugins: [createPinia(), router], stubs: { AdminShell: { template: "<div><slot/></div>" } } } });
  await flushPromises();
  expect(notificationApi.list).toHaveBeenCalledWith("unread", 1, 3);
  expect(wrapper.get(".dashboard-notification-list strong").text()).toBe("希望工厂提交发货");
  expect(wrapper.get(".dashboard-notification-list small").text()).toBe("希望工厂发货：童帽等，总计560件");
  const links = wrapper.findAll(".dashboard-stat-card");
  expect(links[1].attributes("href")).toBe("/shipments?dateFrom=2026-09-06&dateTo=2026-09-06");
  await links[2].trigger("click"); await flushPromises();
  expect(router.currentRoute.value.query.status).toBe("已逾期");
  wrapper.unmount(); vi.useRealTimers();
});

it("limits the dashboard to ten rows and keeps the all-orders link without pagination", async () => {
  vi.spyOn(orderApi, "dashboard").mockResolvedValue({ recentOrders: Array.from({ length: 15 }, (_, index) => order({ orderId: `order-${index}` })), overdueOrders: 0, pendingImportOrders: 0, todayShipments: 0, requestId: "test" });
  vi.spyOn(notificationApi, "unreadCount").mockResolvedValue({ count: 0, requestId: "test" });
  vi.spyOn(notificationApi, "list").mockResolvedValue({ items: [], total: 0, page: 1, pageSize: 3, requestId: "test" });
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: "/", component: HomePage }, { path: "/:pathMatch(.*)*", component: { template: "<div/>" } }] });
  await router.push("/");
  const wrapper = mount(HomePage, { global: { plugins: [createPinia(), router], stubs: { AdminShell: { template: "<div><slot/></div>" } } } });
  await flushPromises();
  expect(wrapper.findAll(".dashboard-order-table tbody tr")).toHaveLength(10);
  expect(wrapper.find(".order-pagination").exists()).toBe(false);
  const link = wrapper.findAll("a").find(item => item.text().includes("查看全部订单"));
  expect(link?.attributes("href")).toBe("/orders");
  wrapper.unmount();
});

it.each(["slow", "failed"])("renders dashboard independently of %s notifications", async (mode) => {
  vi.spyOn(orderApi, "dashboard").mockResolvedValue({ recentOrders: [order()], overdueOrders: 101, todayShipments: 2, pendingImportOrders: 0 } as never);
  vi.spyOn(notificationApi, "unreadCount").mockResolvedValue({ count: 0 } as never);
  vi.spyOn(notificationApi, "list").mockImplementation(() => mode === "failed" ? Promise.reject(new Error("offline")) : new Promise(() => undefined));
  const wrapper = mount(HomePage, { global: { plugins: [createPinia()], stubs: { AdminShell: { template: "<div><slot /></div>" }, RouterLink: { template: "<a><slot /></a>" } } } });
  await flushPromises();
  expect(wrapper.text()).toContain("090#");
  expect(wrapper.text()).toContain("101");
  expect(wrapper.text()).not.toContain("订单看板加载失败");
  wrapper.unmount();
});
