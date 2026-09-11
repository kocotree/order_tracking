import { useRoute } from "vue-router";
import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { contractApi, orderApi, shipmentApi, type Shipment, type Order } from "@/api/client";
import OrderDetailPage from "@/pages/OrderDetailPage.vue";

vi.mock("vue-router", async () => {
  const { reactive } = await import("vue");
  const route = reactive({ params: { orderId: "order-1" }, query: {} });
  return { useRoute: () => route, useRouter: () => ({ replace: vi.fn() }) };
});

const sampleOrder = {
    detailMode: false, details: [],
  orderId: "order-1", orderNo: "092#", source: "manual", orderDate: "2026-08-22", tracker: "青椒",
  contractShipDates: ["2026-09-15"], contractShipDate: "2026-09-15", lifecycle: "DRAFT", displayStatus: "草稿", version: 1,
  totalQuantity: 400, shippedQuantity: 0, pendingQuantity: 400, overQuantity: 0, shortQuantity: 0, progressPercent: 0,
  lines: [{ orderLineId: 1, variantId: "variant-1", skuId: "KQ26721", productName: "轻量防风马甲", propertiesValue: "雾蓝 / 110", category: "服装", imageObjectKey: null, orderQuantity: 400, shippedQuantity: 0, pendingQuantity: 400, overQuantity: 0, shortQuantity: 0, progressPercent: 0, assignments: [{ contractShipDate: "2026-08-30", assignmentId: 1, factoryId: "factory-1", factoryName: "盛泰", assignedQuantity: 400, shippedQuantity: 0, pendingQuantity: 400, overQuantity: 0, shortQuantity: 0, progressPercent: 0 }] }],
  factoryProgress: [{ factoryId: "factory-1", factoryName: "盛泰", orderQuantity: 400, shippedQuantity: 0, pendingQuantity: 400, overQuantity: 0, shortQuantity: 0, progressPercent: 0 }],
  validationIssues: [], createdAt: "2026-08-22T08:00:00Z", updatedAt: "2026-08-22T08:00:00Z", requestId: "request-1",
} satisfies Order;

afterEach(() => vi.restoreAllMocks());
beforeEach(() => {
  useRoute().params.orderId = "order-1";
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute("open", ""); };
  HTMLDialogElement.prototype.close = function () { this.removeAttribute("open"); };

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
    expect(productTable.findAll("thead th")).toHaveLength(11);
    expect(productTable.findAll("thead th").map((cell) => cell.text())).not.toContain("图片");
    for (const row of productTable.findAll("tbody tr")) {
      expect(row.findAll("td")).toHaveLength(11);
    }


    expect(wrapper.attributes("data-title")).toBe("订单详情 · 092#");
    expect(wrapper.findAll(".detail-summary-grid > div")).toHaveLength(6);
    expect(wrapper.findAll(".product-detail-table th")).toHaveLength(11);
    expect(wrapper.findAll(".product-detail-table .data-grid-sort-button")).toHaveLength(10);
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

it("allows only the source detail contract date without exposing whole-order publishing", async () => {
  vi.spyOn(orderApi, "get").mockResolvedValue({ ...sampleOrder, source: "feishu", detailMode: true,
    tracker: null, totalQuantity: null, shippedQuantity: null, pendingQuantity: null, lines: [], factoryProgress: [],
    details: [{ detailId: "source-1", origin: "feishu", sourceSkuId: "RAW-SKU", productName: "未匹配产品",
      propertiesValue: "蓝色", category: "帽子", factoryName: "未匹配厂", matchedVariantId: null,
      matchedFactoryId: null, orderQuantity: null, shippedQuantity: null, pendingQuantity: null,
      progressPercent: null, sourceTracker: null, contractShipDate: null, dispatchState: "UNASSIGNED",
      version: 1, rawFields: { "下单数": "待补" } }],
  });
  const wrapper = mount(OrderDetailPage, { global: { stubs: { AdminShell: { template: "<div><slot /></div>" }, RouterLink: true } } });
  await flushPromises();
  const table = wrapper.get('.product-detail-table');
  expect(table.text()).toContain("RAW-SKU");
  expect(table.text()).toContain("未匹配厂");
  expect(table.findAll('input:not([type="checkbox"]), select')).toHaveLength(1);
  expect(table.get('input[type="date"]').attributes('type')).toBe('date');
  expect(wrapper.text()).not.toContain("发布订单");
  expect(wrapper.findAll('.detail-summary-number').map(cell => cell.text())).toEqual(["—", "—", "—"]);
});


const sourceOrder: Order = { ...sampleOrder, source: "feishu", detailMode: true, lines: [], factoryProgress: [],
  details: [{ detailId: "source-89", origin: "feishu", sourceSkuId: "RAW-SKU", productName: "测试产品",
    propertiesValue: "蓝色", category: "帽子", factoryName: "测试厂", matchedVariantId: null,
    matchedFactoryId: null, orderQuantity: 100, shippedQuantity: 0, pendingQuantity: 100,
    progressPercent: 0, sourceTracker: "松子", contractShipDate: "2026-09-15", dispatchState: "UNASSIGNED",
    version: 1, rawFields: {} }],
};
const sourceDiff = { previewId: "preview89", version: 1, expiresAt: "2026-09-11T12:05:00",
  differences: [{ detailId: "source-89", label: "第1条 · 蓝色", field: "已发数量", before: 0, after: 20 }],
};
const mountSource = () => mount(OrderDetailPage, { global: { stubs: {
  AdminShell: { template: "<div><slot /></div>" }, RouterLink: true,
} } });
const updateButton = (wrapper: ReturnType<typeof mountSource>) => wrapper.findAll('button').find(b => b.text() === '更新未派工明细')!;
const dispatchButton = (wrapper: ReturnType<typeof mountSource>) => wrapper.findAll('button').find(b => b.text().startsWith('派工（'))!;

it("preserves failed date input and prevents refresh until the save succeeds", async () => {
  vi.spyOn(orderApi, "get").mockResolvedValue(sourceOrder);
  const save = vi.spyOn(orderApi, "saveDetailDate").mockRejectedValueOnce(new Error("offline"))
    .mockResolvedValueOnce({ ...sourceOrder, version: 2, details: [{ ...sourceOrder.details[0], version: 2, contractShipDate: null }] });
  const wrapper = mountSource(); await flushPromises();
  const input = wrapper.get('input[type="date"]');
  await input.setValue(""); await input.trigger('blur'); await flushPromises();
  expect(wrapper.text()).toContain('日期保存失败');
  expect((input.element as HTMLInputElement).value).toBe('');
  expect(updateButton(wrapper).attributes('disabled')).toBeDefined();
  expect(wrapper.get('.detail-due-date').text()).toBe('2026-09-15');
  await input.trigger('blur'); await flushPromises();
  expect(save).toHaveBeenLastCalledWith('order-1', 'source-89', 1, 1, null);
  expect(updateButton(wrapper).attributes('disabled')).toBeUndefined();
  wrapper.unmount();
});

it("previews without updating, cancels without confirmation, and retries with the same key", async () => {
  vi.spyOn(orderApi, "get").mockResolvedValue(sourceOrder);
  vi.spyOn(orderApi, "previewSource").mockResolvedValue(sourceDiff);
  const confirm = vi.spyOn(orderApi, "confirmSource").mockRejectedValueOnce(new Error("offline"))
    .mockResolvedValueOnce({ ...sourceOrder, version: 2, details: [{ ...sourceOrder.details[0], shippedQuantity: 20 }] });
  const wrapper = mountSource(); await flushPromises();
  await updateButton(wrapper).trigger('click'); await flushPromises();
  expect(wrapper.get('dialog table').text()).toContain('已发数量020');
  expect(wrapper.get('.product-detail-table tbody').text()).toContain('测试产品');
  await wrapper.get('dialog .order-secondary-button').trigger('click');
  expect(confirm).not.toHaveBeenCalled();
  await updateButton(wrapper).trigger('click'); await flushPromises();
  await wrapper.get('dialog .order-primary-button').trigger('click'); await flushPromises();
  expect(wrapper.get('dialog').text()).toContain('来源更新失败');
  await wrapper.get('dialog .order-primary-button').trigger('click'); await flushPromises();
  expect(confirm.mock.calls[0]).toEqual(confirm.mock.calls[1]);
  expect(wrapper.get('dialog').attributes('open')).toBeUndefined();
  wrapper.unmount();
});

it("ignores a late source response after navigating to another order", async () => {
  vi.spyOn(orderApi, "get").mockImplementation(async (id) => ({ ...sourceOrder, orderId: id, orderNo: id }));
  let finish!: (value: typeof sourceDiff) => void;
  vi.spyOn(orderApi, "previewSource").mockReturnValue(new Promise(resolve => { finish = resolve; }));
  const wrapper = mountSource(); await flushPromises();
  await updateButton(wrapper).trigger('click');
  useRoute().params.orderId = 'order-2'; await flushPromises();
  finish(sourceDiff); await flushPromises();
  expect(wrapper.get('dialog').attributes('open')).toBeUndefined();
  expect(wrapper.text()).not.toContain('来源资料有变化');
  wrapper.unmount();
});

it("does not expose source refresh or date inputs for assigned details", async () => {
  vi.spyOn(orderApi, "get").mockResolvedValue({ ...sourceOrder, details: [{ ...sourceOrder.details[0], dispatchState: "ASSIGNED" }] });
  const wrapper = mountSource(); await flushPromises();
  expect(wrapper.find('input[type="date"]').exists()).toBe(false);
  expect(updateButton(wrapper)).toBeUndefined();
  wrapper.unmount();
});

it("confirms changed sources independently before dispatching the selected details", async () => {
  vi.spyOn(orderApi, "get").mockResolvedValue(sourceOrder);
  const updatedOrder = {
    ...sourceOrder,
    version: 2,
    details: [{ ...sourceOrder.details[0], shippedQuantity: 20, pendingQuantity: 80, version: 2 }],
  };
  const dispatchedOrder = {
    ...updatedOrder,
    version: 3,
    lifecycle: "PUBLISHED" as const,
    details: [{ ...updatedOrder.details[0], dispatchState: "ASSIGNED" }],
  };
  const preview = vi.spyOn(orderApi, "dispatchPreview")
    .mockResolvedValueOnce({
      previewId: null,
      version: 1,
      expiresAt: null,
      requiresSourceConfirmation: true,
      sourcePreview: sourceDiff,
      validations: [],
      allOk: false,
    })
    .mockResolvedValueOnce({
      previewId: "dispatch-90",
      version: 2,
      expiresAt: "2026-09-11T12:05:00Z",
      requiresSourceConfirmation: false,
      sourcePreview: null,
      validations: [{ detailId: "source-89", label: "第1条 · 蓝色", factoryName: "测试厂", passes: true, issues: [] }],
      allOk: true,
    });
  const confirmSource = vi.spyOn(orderApi, "confirmSource").mockResolvedValue(updatedOrder);
  const confirmDispatch = vi.spyOn(orderApi, "dispatchConfirm").mockResolvedValue(dispatchedOrder);

  const wrapper = mountSource();
  await flushPromises();
  await wrapper.get('input[aria-label="选择第1条"]').setValue(true);
  await dispatchButton(wrapper).trigger("click");
  await flushPromises();

  expect(wrapper.get(".dispatch-modal").text()).toContain("来源资料有变化");
  await wrapper.get(".dispatch-modal .order-primary-button").trigger("click");
  await flushPromises();

  expect(confirmSource).toHaveBeenCalledWith("order-1", 1, "preview89", expect.any(String));
  expect(preview).toHaveBeenLastCalledWith("order-1", 2, ["source-89"]);
  expect(wrapper.get(".dispatch-modal").text()).toContain("所选明细校验通过");

  await wrapper.get(".dispatch-modal .order-primary-button").trigger("click");
  await flushPromises();
  expect(confirmDispatch).toHaveBeenCalledWith("order-1", 2, "dispatch-90", expect.any(String));
  expect(wrapper.text()).toContain("全部派工");
  wrapper.unmount();
});
