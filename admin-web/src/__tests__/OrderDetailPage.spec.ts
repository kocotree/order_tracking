import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";

import { orderApi, type Order } from "@/api/client";
import OrderDetailPage from "@/pages/OrderDetailPage.vue";

vi.mock("vue-router", () => ({
  useRoute: () => ({ params: { orderId: "order-1" } }),
  useRouter: () => ({ replace: vi.fn() }),
}));

const sampleOrder = {
  orderId: "order-1", orderNo: "092#", source: "manual", orderDate: "2026-08-22", tracker: "青椒",
  contractShipDate: "2026-09-15", lifecycle: "DRAFT", displayStatus: "草稿", version: 1,
  totalQuantity: 400, shippedQuantity: 0, pendingQuantity: 400, overQuantity: 0, shortQuantity: 0, progressPercent: 0,
  lines: [{ orderLineId: 1, variantId: "variant-1", skuId: "KQ26721", productName: "轻量防风马甲", propertiesValue: "雾蓝 / 110", category: "服装", imageObjectKey: null, orderQuantity: 400, shippedQuantity: 0, pendingQuantity: 400, overQuantity: 0, shortQuantity: 0, progressPercent: 0, assignments: [{ assignmentId: 1, factoryId: "factory-1", factoryName: "盛泰", assignedQuantity: 400, shippedQuantity: 0, pendingQuantity: 400, overQuantity: 0, shortQuantity: 0, progressPercent: 0 }] }],
  factoryProgress: [{ factoryId: "factory-1", factoryName: "盛泰", orderQuantity: 400, shippedQuantity: 0, pendingQuantity: 400, overQuantity: 0, shortQuantity: 0, progressPercent: 0 }],
  validationIssues: [], createdAt: "2026-08-22T08:00:00Z", updatedAt: "2026-08-22T08:00:00Z", requestId: "request-1",
} satisfies Order;

afterEach(() => vi.restoreAllMocks());

describe("order detail prototype alignment", () => {
  it("uses the approved summary and ten-column detail table without opening S06 export", async () => {
    vi.spyOn(orderApi, "get").mockResolvedValue(sampleOrder);
    const wrapper = mount(OrderDetailPage, { global: { stubs: { AdminShell: { props: ["title"], template: '<div :data-title="title"><slot /></div>' }, RouterLink: { props: ["to"], template: "<a><slot /></a>" } } } });
    await flushPromises();

    expect(wrapper.attributes("data-title")).toBe("订单详情 · 092#");
    expect(wrapper.findAll(".detail-summary-grid > div")).toHaveLength(6);
    expect(wrapper.findAll(".product-detail-table th")).toHaveLength(10);
    expect(wrapper.findAll(".product-detail-table .data-grid-sort-button")).toHaveLength(8);
    expect(wrapper.text()).toContain("编辑草稿");
    expect(wrapper.text()).toContain("删除订单");
    expect(wrapper.text()).not.toContain("导出加工合同");
    expect(wrapper.text()).not.toContain("工厂派工与进度");
    expect(wrapper.text()).not.toContain("操作日志");
  });
});
