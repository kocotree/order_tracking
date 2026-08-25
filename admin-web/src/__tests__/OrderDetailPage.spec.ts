import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { contractApi, orderApi, type Order } from "@/api/client";
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
beforeEach(() => {
  vi.spyOn(orderApi, "auditLogs").mockResolvedValue({
    items: [{ action: "order.imported_from_feishu", changes: {}, actorId: "admin-1", operatorName: "松子", content: "从飞书导入订单：订单数量 400，初始已发数量 100，未发数量 300。", sourceTerminal: "web_admin", createdAt: "2026-08-25T01:00:00Z" }],
    total: 1,
    requestId: "audit-request",
  });
});

describe("order detail prototype alignment", () => {
  it("shows the S06 export entry disabled for draft orders", async () => {
    vi.spyOn(orderApi, "get").mockResolvedValue(sampleOrder);
    const wrapper = mount(OrderDetailPage, { global: { stubs: { AdminShell: { props: ["title"], template: '<div :data-title="title"><slot /></div>' }, RouterLink: { props: ["to"], template: "<a><slot /></a>" } } } });
    await flushPromises();

    expect(wrapper.attributes("data-title")).toBe("订单详情 · 092#");
    expect(wrapper.findAll(".detail-summary-grid > div")).toHaveLength(6);
    expect(wrapper.findAll(".product-detail-table th")).toHaveLength(10);
    expect(wrapper.findAll(".product-detail-table .data-grid-sort-button")).toHaveLength(8);
    expect(wrapper.text()).not.toContain("编辑草稿");
    expect(wrapper.text()).not.toContain("删除订单");
    const contractButton = wrapper.find('[data-testid="contract-export-open"]');
    expect(contractButton.attributes("disabled")).toBeDefined();
    expect(contractButton.attributes("title")).toContain("请先发布订单");
    expect(wrapper.text()).not.toContain("工厂派工与进度");
    expect(wrapper.text()).toContain("操作日志");
    expect(wrapper.text()).toContain("松子");
    expect(wrapper.text()).toContain("从飞书导入订单：订单数量 400，初始已发数量 100，未发数量 300。");
  });

  it("opens the confirmed single-factory export dialog for a published unshipped order", async () => {
    vi.spyOn(orderApi, "get").mockResolvedValue({ ...sampleOrder, lifecycle: "PUBLISHED", displayStatus: "未完成" });
    vi.spyOn(contractApi, "list").mockResolvedValue({
      items: [{ factoryId: "factory-1", factoryName: "盛泰", contractReady: true, missingContractFields: [], eligible: true, ineligibleReason: null, contractNo: null, signingDate: null }],
      requestId: "contract-list-request",
    });
    const wrapper = mount(OrderDetailPage, { global: { stubs: { AdminShell: { props: ["title"], template: '<div :data-title="title"><slot /></div>' }, RouterLink: { props: ["to"], template: "<a><slot /></a>" } } } });
    await flushPromises();

    const exportButton = wrapper.find('[data-testid="contract-export-open"]');
    expect(exportButton.exists()).toBe(true);
    expect(exportButton.attributes("disabled")).toBeUndefined();
    await exportButton.trigger("click");

    expect(wrapper.text()).toContain("合同资料");
    expect(wrapper.text()).toContain("首次导出后生成");
    expect(wrapper.find('input[type="date"]').attributes("readonly")).toBeUndefined();
  });

  it("re-exports with the immutable signing date and downloads the generated workbook", async () => {
    vi.spyOn(orderApi, "get").mockResolvedValue({ ...sampleOrder, lifecycle: "PUBLISHED", displayStatus: "未完成" });
    vi.spyOn(contractApi, "list").mockResolvedValue({
      items: [{ factoryId: "factory-1", factoryName: "盛泰", contractReady: true, missingContractFields: [], eligible: true, ineligibleReason: null, contractNo: "20260824-KK-ST", signingDate: "2026-08-24" }],
      requestId: "contract-list-request",
    });
    const exportSpy = vi.spyOn(contractApi, "export").mockResolvedValue({ exportId: "export-1", contractId: "contract-1", contractNo: "20260824-KK-ST", signingDate: "2026-08-24", filename: "20260824-KK-ST.xlsx", status: "READY", downloadUrl: "/api/v1/admin/contract-exports/export-1/download", requestId: "contract-export-request" });
    const downloadSpy = vi.spyOn(contractApi, "download").mockResolvedValue();
    const wrapper = mount(OrderDetailPage, { global: { stubs: { AdminShell: { props: ["title"], template: '<div :data-title="title"><slot /></div>' }, RouterLink: { props: ["to"], template: "<a><slot /></a>" } } } });
    await flushPromises();

    await wrapper.find('[data-testid="contract-export-open"]').trigger("click");
    expect(wrapper.find('input[type="date"]').attributes("readonly")).toBeDefined();
    await wrapper.find(".contract-export-dialog .order-primary-button").trigger("click");
    await flushPromises();

    expect(exportSpy).toHaveBeenCalledWith("order-1", "factory-1", "2026-08-24");
    expect(downloadSpy).toHaveBeenCalledOnce();
    expect(wrapper.find(".contract-export-dialog").exists()).toBe(false);
  });
});
