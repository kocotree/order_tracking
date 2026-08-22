import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";

import { identityApi, orderApi, type Order } from "@/api/client";
import OrdersPage from "@/pages/OrdersPage.vue";

const sampleOrder = {
  orderId: "order-1", orderNo: "090#", source: "manual", orderDate: "2026-08-20", tracker: "橄榄",
  contractShipDate: "2026-08-25", lifecycle: "PUBLISHED", displayStatus: "未完成", version: 1,
  totalQuantity: 100, shippedQuantity: 20, pendingQuantity: 80, overQuantity: 0, shortQuantity: 0, progressPercent: 20,
  lines: [{ orderLineId: 1, variantId: "variant-1", skuId: "SKU-1", productName: "晴雨机能风衣", propertiesValue: "蓝色 / 120", category: "童装春夏", imageObjectKey: null, orderQuantity: 100, shippedQuantity: 20, pendingQuantity: 80, overQuantity: 0, shortQuantity: 0, progressPercent: 20, assignments: [] }],
  factoryProgress: [{ factoryId: "factory-1", factoryName: "启宏", orderQuantity: 100, shippedQuantity: 20, pendingQuantity: 80, overQuantity: 0, shortQuantity: 0, progressPercent: 20 }],
  validationIssues: [], createdAt: "2026-08-20T08:00:00Z", updatedAt: "2026-08-20T08:00:00Z", requestId: "request-1",
} satisfies Order;

afterEach(() => vi.restoreAllMocks());

describe("order list prototype alignment", () => {
  it("keeps all filters visible, hides more operations, and sends category, multi-factory, and table sorts", async () => {
    vi.spyOn(identityApi, "listFactories").mockResolvedValue({ items: [{ factoryId: "factory-1", factoryName: "启宏" }], total: 1 } as never);
    const listSpy = vi.spyOn(orderApi, "list").mockResolvedValue({ items: [sampleOrder], total: 1, page: 1, pageSize: 10, requestId: "request-list" });
    const wrapper = mount(OrdersPage, { global: { stubs: { AdminShell: { template: "<div><slot /></div>" }, RouterLink: { props: ["to"], template: "<a><slot /></a>" } } } });
    await flushPromises();

    expect(wrapper.get('.order-list-search-field input').attributes('placeholder')).toBe("输入订单编号、产品名称或颜色/规格");
    expect(wrapper.text()).not.toContain("更多操作");
    expect(wrapper.text()).not.toContain("手工新建订单");
    expect(wrapper.text()).toContain("服装");
    expect(wrapper.findAll('.data-grid-sort-button')).toHaveLength(9);

    await wrapper.get('.order-select-field select').setValue("服装");
    await flushPromises();
    await wrapper.get('.order-multiselect-trigger').trigger('click');
    await wrapper.get('.order-multiselect-option input').setValue(true);
    await flushPromises();
    const categoryHeader = wrapper.findAll('.data-grid-sort-button').find((item) => item.text().includes("分类"));
    await categoryHeader?.trigger('click');
    await flushPromises();

    expect(listSpy).toHaveBeenLastCalledWith(expect.objectContaining({ category: "服装", factoryIds: ["factory-1"], sortBy: "categoryAsc" }));
  });
});
