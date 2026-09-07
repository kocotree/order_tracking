import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { contractApi, orderApi, shipmentApi, type Shipment, type Order } from "@/api/client";
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
  vi.spyOn(shipmentApi, "list").mockResolvedValue({ items: [], total: 0 });
  vi.spyOn(orderApi, "auditLogs").mockResolvedValue({
    items: [{ action: "order.imported_from_feishu", changes: {}, actorId: "admin-1", operatorName: "松子", content: "从飞书导入订单：订单数量 400，初始已发数量 100，未发数量 300。", sourceTerminal: "web", createdAt: "2026-08-25T01:00:00Z" }],
    total: 1,
    requestId: "audit-request",
  });
});

describe("order detail prototype alignment", () => {
  it("shows the S06 export entry disabled for draft orders", async () => {
    vi.spyOn(orderApi, "get").mockResolvedValue(sampleOrder);
    const wrapper = mount(OrderDetailPage, { global: { stubs: { AdminShell: { props: ["title"], template: '<div :data-title="title"><slot /></div>' }, RouterLink: { props: ["to"], template: "<a><slot /></a>" } } } });
    await flushPromises();
    const productTable = wrapper.get(".product-detail-table");
    expect(productTable.findAll("thead th")).toHaveLength(9);
    expect(productTable.findAll("thead th").map((cell) => cell.text())).not.toContain("图片");
    for (const row of productTable.findAll("tbody tr")) {
      expect(row.findAll("td")).toHaveLength(9);
    }


    expect(wrapper.attributes("data-title")).toBe("订单详情 · 092#");
    expect(wrapper.findAll(".detail-summary-grid > div")).toHaveLength(6);
    expect(wrapper.findAll(".product-detail-table th")).toHaveLength(9);
    expect(wrapper.findAll(".product-detail-table .data-grid-sort-button")).toHaveLength(8);
    expect(wrapper.text()).not.toContain("编辑草稿");
    expect(wrapper.text()).not.toContain("删除订单");
    const contractButton = wrapper.find('[data-testid="contract-export-open"]');
    expect(contractButton.attributes("disabled")).toBeDefined();
    expect(contractButton.attributes("title")).toContain("请先发布订单");
    expect(wrapper.text()).not.toContain("工厂派工与进度");
    expect(wrapper.text()).toContain("操作记录（1）");
    expect(wrapper.find(".order-audit-list").exists()).toBe(false);
  });

  it("collapses order operation records to one row and toggles the full list", async () => {
    vi.spyOn(orderApi, "get").mockResolvedValue(sampleOrder);
    const wrapper = mount(OrderDetailPage, { global: { stubs: { AdminShell: { props: ["title"], template: '<div :data-title="title"><slot /></div>' }, RouterLink: { props: ["to"], template: "<a><slot /></a>" } } } });
    await flushPromises();

    const toggle = wrapper.find(".order-audit-toggle");
    expect(toggle.attributes("aria-expanded")).toBe("false");
    expect(wrapper.find(".order-audit-list").exists()).toBe(false);
    expect(wrapper.text()).not.toContain("从飞书导入订单：订单数量 400，初始已发数量 100，未发数量 300。");

    await toggle.trigger("click");
    expect(toggle.attributes("aria-expanded")).toBe("true");
    expect(wrapper.find(".order-audit-list").exists()).toBe(true);
    expect(wrapper.findAll(".order-audit-list .shipment-log-item")).toHaveLength(1);
    expect(wrapper.find(".order-audit-list .shipment-log-dot").exists()).toBe(true);
    expect(wrapper.text()).toContain("松子");
    expect(wrapper.text()).toContain("管理员网页");
    expect(wrapper.text()).toContain("从飞书导入订单：订单数量 400，初始已发数量 100，未发数量 300。");

    await toggle.trigger("click");
    expect(wrapper.find(".order-audit-list").exists()).toBe(false);
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


describe("related shipments", () => {
  function mountPage() {
    return mount(OrderDetailPage, { global: { stubs: { AdminShell: { template: "<div><slot /></div>" }, RouterLink: { props: ["to"], template: '<a :href="to"><slot /></a>' } } } });
  }

  it.each(["SHIPPED", "VOID_PENDING", "VOIDED"])("keeps %s records and both detail links in the four-column list", async (status) => {
    vi.spyOn(orderApi, "get").mockResolvedValue(sampleOrder);
    vi.mocked(shipmentApi.list).mockResolvedValue({ items: [{ shipmentId: "shipment-1", shipmentNo: "FH20260905-001", businessDate: "2026-09-05", totalQuantity: 23, status } as Shipment], total: 1 });
    const wrapper = mountPage();
    await flushPromises();
    expect(shipmentApi.list).toHaveBeenCalledWith("order-1");
    const table = wrapper.get(".related-shipment-table");
    expect(table.findAll("th").map((cell) => cell.text())).toEqual(["发货单号", "发货日期", "发货数量", "操作"]);
    expect(table.findAll("tbody td").map((cell) => cell.text())).toEqual(["FH20260905-001", "2026-09-05", "23", "详情"]);
    expect(table.findAll('a[href="/shipments/shipment-1"]')).toHaveLength(2);
  });

  it.each([false, true])("spans all four columns for empty/error feedback (%s)", async (failed) => {
    vi.spyOn(orderApi, "get").mockResolvedValue(sampleOrder);
    if (failed) vi.mocked(shipmentApi.list).mockRejectedValue(new Error("offline"));
    const wrapper = mountPage();
    await flushPromises();
    const cell = wrapper.get(".related-shipment-table tbody td");
    expect(cell.attributes("colspan")).toBe("4");
    expect(cell.text()).toContain(failed ? "关联发货单加载失败" : "当前订单暂无关联发货单");
    if (failed) expect(cell.attributes("role")).toBe("alert");
  });

  it("keeps the page loading until related shipments resolve, then shows the four-column empty state", async () => {
    vi.spyOn(orderApi, "get").mockResolvedValue(sampleOrder);
    let resolveList!: (value: Awaited<ReturnType<typeof shipmentApi.list>>) => void;
    vi.mocked(shipmentApi.list).mockReturnValue(new Promise((resolve) => { resolveList = resolve; }));
    const wrapper = mountPage();
    await flushPromises();
    expect(wrapper.get(".page-state").text()).toBe("正在加载订单详情…");
    expect(wrapper.find(".related-shipment-table").exists()).toBe(false);
    resolveList({ items: [], total: 0 });
    await flushPromises();
    expect(wrapper.find(".page-state").exists()).toBe(false);
    expect(wrapper.get(".related-shipment-table tbody td").attributes("colspan")).toBe("4");
    expect(wrapper.get(".related-shipment-table tbody").text()).toBe("当前订单暂无关联发货单");
  });
});
