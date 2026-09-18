import { createRouter, createMemoryHistory } from "vue-router";
import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";

import { identityApi, orderApi, type Order } from "@/api/client";
import OrdersPage from "@/pages/OrdersPage.vue";

const sampleOrder = {
  detailMode: false, details: [], orderId: "order-1", orderNo: "090#", source: "manual", orderDate: "2026-08-20", tracker: "橄榄",
  trackers: ["橄榄", "松子"],
  contractShipDates: ["2026-08-25"], contractShipDate: "2026-08-25", lifecycle: "PUBLISHED", displayStatus: "未完成", dispatchStatus: "部分派工", version: 1,
  totalQuantity: 100, shippedQuantity: 20, pendingQuantity: 80, overQuantity: 0, shortQuantity: 0, progressPercent: 20,
  lines: [{ orderLineId: 1, variantId: "variant-1", skuId: "SKU-1", itemNumber: "ITEM-1", productName: "晴雨机能风衣", propertiesValue: "蓝色 / 120", category: "童装春夏", imageObjectKey: null, orderQuantity: 100, shippedQuantity: 20, pendingQuantity: 80, overQuantity: 0, shortQuantity: 0, progressPercent: 20, assignments: [] }],
  factoryProgress: [{ factoryId: "factory-1", factoryName: "启宏", orderQuantity: 100, shippedQuantity: 20, pendingQuantity: 80, overQuantity: 0, shortQuantity: 0, progressPercent: 20 }],
  validationIssues: [], createdAt: "2026-08-20T08:00:00Z", updatedAt: "2026-08-20T08:00:00Z", requestId: "request-1",
} satisfies Order;

afterEach(() => vi.restoreAllMocks());

describe("order list prototype alignment", () => {
  it("keeps all filters visible, hides more operations, and sends category, multi-factory, and table sorts", async () => {
    vi.spyOn(identityApi, "listFactoryOptions").mockResolvedValue({ items: [{ factoryId: "factory-1", factoryName: "启宏" }], total: 1 } as never);
    const listSpy = vi.spyOn(orderApi, "list").mockResolvedValue({ items: [sampleOrder], total: 1, page: 1, pageSize: 10, requestId: "request-list" });
    const wrapper = mount(OrdersPage, { global: { stubs: { AdminShell: { template: "<div><slot /></div>" }, RouterLink: { props: ["to"], template: "<a><slot /></a>" } } } });
    await flushPromises();

    expect(wrapper.get('.order-list-search-field input').attributes('placeholder')).toBe("输入订单编号、产品名称或颜色/规格");
    expect(wrapper.text()).not.toContain("更多操作");
    expect(wrapper.text()).not.toContain("手工新建订单");
    expect(wrapper.text()).toContain("童装春夏");
    expect(wrapper.get('.order-select-field select').findAll('option').map((item) => item.text())).toEqual([
      "全部分类", "童帽春夏", "童配春夏", "童装春夏", "童帽秋冬", "童配秋冬", "童装秋冬", "儿童手套",
    ]);
    expect(wrapper.findAll('.data-grid-sort-button')).toHaveLength(10);
    expect(wrapper.get('.status-badge').classes()).toContain('is-info');
    expect(wrapper.findAll('.tracker-tag').map((item) => item.text())).toEqual(['橄榄', '松子']);
    expect(wrapper.get('select[aria-label="派工状态"]').findAll('option').map((item) => item.text())).toEqual([
      "全部派工状态", "全部派工", "部分派工", "未派工",
    ]);
    expect(wrapper.find('input[type="date"]').exists()).toBe(false);
    expect(wrapper.get('.order-dispatch-status').text()).toBe("部分派工");
    expect(wrapper.get('.dispatch-status-badge').attributes('data-status')).toBe("部分派工");
    expect(wrapper.findAll('thead th').map((item) => item.text())).toEqual([
      "序号", "订单编号", "产品名称", "分类", "跟单人员", "工厂", "合同出货时间",
      "发货进度", "已发/订单数", "派工状态", "状态", "操作",
    ]);

    await wrapper.get('.order-select-field select').setValue("童装春夏");
    await flushPromises();
    await wrapper.get('.order-multiselect-trigger').trigger('click');
    await wrapper.get('.order-multiselect-option input').setValue(true);
    await flushPromises();
    await wrapper.get('select[aria-label="派工状态"]').setValue("部分派工");
    await flushPromises();
    const categoryHeader = wrapper.findAll('.data-grid-sort-button').find((item) => item.text().includes("分类"));
    await categoryHeader?.trigger('click');
    await flushPromises();
    const dispatchHeader = wrapper.findAll('.data-grid-sort-button').find((item) => item.text().includes("派工状态"));
    await dispatchHeader?.trigger('click');
    await flushPromises();

    expect(listSpy).toHaveBeenLastCalledWith(expect.objectContaining({ category: "童装春夏", factoryIds: ["factory-1"], dispatchStatus: "部分派工", sortBy: "dispatchStatusAsc" }));
  });
});

it("opens the overdue tab from the dashboard query", async () => {
  vi.spyOn(identityApi, "listFactoryOptions").mockResolvedValue({ items: [], total: 0 } as never);
  const list = vi.spyOn(orderApi, "list").mockResolvedValue({ items: [], total: 0 } as never);
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: "/orders", component: OrdersPage }] });
  await router.push("/orders?status=已逾期");
  const wrapper = mount(OrdersPage, { global: { plugins: [router], stubs: { AdminShell: { template: "<div><slot/></div>" } } } });
  await flushPromises();
  expect(list).toHaveBeenCalledWith(expect.objectContaining({ status: "已逾期" }));
  expect(wrapper.get(".order-status-tab.is-active").text()).toBe("已逾期");
  wrapper.unmount();
});

it("restores filters from the URL and carries them into order details", async () => {
  vi.spyOn(identityApi, "listFactoryOptions").mockResolvedValue({ items: [], total: 0 } as never);
  const list = vi.spyOn(orderApi, "list").mockResolvedValue({ items: [sampleOrder], total: 11, page: 2, pageSize: 10 } as never);
  const router = createRouter({ history: createMemoryHistory(), routes: [
    { path: "/orders", component: OrdersPage },
    { path: "/orders/:orderId", component: { template: "<div />" } },
  ] });
  await router.push({ path: "/orders", query: {
    keyword: "蓝色", status: "未完成", category: "童装春夏", factoryId: ["factory-1", "factory-2"],
    tracker: ["松子", "橄榄"], dispatchStatus: "部分派工", sortBy: "categoryDesc", page: "2",
  } });
  const wrapper = mount(OrdersPage, { global: { plugins: [router], stubs: { AdminShell: { template: "<div><slot/></div>" } } } });
  await flushPromises();

  expect(list).toHaveBeenCalledWith(expect.objectContaining({
    keyword: "蓝色", status: "未完成", category: "童装春夏", factoryIds: ["factory-1", "factory-2"],
    trackers: ["松子", "橄榄"], dispatchStatus: "部分派工", sortBy: "categoryDesc", page: 2,
  }));
  const detailUrl = new URL(wrapper.get('a[href^="/orders/order-1"]').attributes("href")!, "https://example.test");
  expect(detailUrl.searchParams.get("keyword")).toBe("蓝色");
  expect(detailUrl.searchParams.getAll("factoryId")).toEqual(["factory-1", "factory-2"]);
  expect(detailUrl.searchParams.getAll("tracker")).toEqual(["松子", "橄榄"]);
  expect(detailUrl.searchParams.get("dispatchStatus")).toBe("部分派工");
  expect(detailUrl.searchParams.get("page")).toBe("2");
  wrapper.unmount();
});

it("renders orders before slow factory options and ignores stale list responses", async () => {
  let resolveFactories!: (value: never) => void;
  vi.spyOn(identityApi, "listFactoryOptions").mockImplementation(() => new Promise((resolve) => { resolveFactories = resolve; }));
  let resolveOld!: (value: never) => void;
  const list = vi.spyOn(orderApi, "list")
    .mockImplementationOnce(() => new Promise((resolve) => { resolveOld = resolve; }))
    .mockResolvedValue({ items: [sampleOrder], total: 1 } as never);
  const wrapper = mount(OrdersPage, { global: { stubs: { AdminShell: { template: "<div><slot /></div>" }, RouterLink: { template: "<a><slot /></a>" } } } });
  expect(list).toHaveBeenCalledTimes(1);
  await wrapper.get(".order-filter-form").trigger("submit");
  await flushPromises();
  expect(wrapper.text()).toContain("090#");
  expect(wrapper.text()).not.toContain("正在加载订单");
  resolveOld({ items: [], total: 0 } as never);
  resolveFactories({ items: [{ factoryId: "other", factoryName: "非当前页工厂", supplierNumber: "S2" }], total: 1 } as never);
  await flushPromises();
  expect(wrapper.text()).toContain("090#");
  await wrapper.get(".order-multiselect-trigger").trigger("click");
  expect(wrapper.text()).toContain("非当前页工厂");
  expect(list).toHaveBeenCalledTimes(2);
  wrapper.unmount();
});

it("does not block orders when factory options fail", async () => {
  vi.spyOn(identityApi, "listFactoryOptions").mockRejectedValue(new Error("offline"));
  const list = vi.spyOn(orderApi, "list").mockResolvedValue({ items: [sampleOrder], total: 1 } as never);
  const wrapper = mount(OrdersPage, { global: { stubs: { AdminShell: { template: "<div><slot /></div>" }, RouterLink: { template: "<a><slot /></a>" } } } });
  await flushPromises();
  expect(wrapper.text()).toContain("090#");
  expect(list).toHaveBeenCalledTimes(1);
  wrapper.unmount();
});

it("returns to the last valid page when the result shrinks", async () => {
  vi.spyOn(identityApi, "listFactoryOptions").mockResolvedValue({ items: [], total: 0 });
  const list = vi.spyOn(orderApi, "list")
    .mockResolvedValueOnce({ items: [sampleOrder], total: 11 } as never)
    .mockResolvedValueOnce({ items: [], total: 10 } as never)
    .mockResolvedValue({ items: [sampleOrder], total: 10 } as never);
  const wrapper = mount(OrdersPage, { global: { stubs: { AdminShell: { template: "<div><slot /></div>" }, RouterLink: { template: "<a><slot /></a>" } } } });
  await flushPromises();
  const second = wrapper.findAll("button").find((button) => button.text() === "2");
  expect(second).toBeDefined();
  await second!.trigger("click");
  await flushPromises();
  expect(list).toHaveBeenLastCalledWith(expect.objectContaining({ page: 1 }));
  expect(wrapper.text()).toContain("090#");
  expect(list).toHaveBeenCalledTimes(3);
  wrapper.unmount();
});
