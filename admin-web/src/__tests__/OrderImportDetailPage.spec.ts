import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";

import { identityApi, orderImportApi, type ImportCandidate } from "@/api/client";
import OrderImportDetailPage from "@/pages/OrderImportDetailPage.vue";

const router = vi.hoisted(() => ({ push: vi.fn() }));

vi.mock("vue-router", () => ({
  useRoute: () => ({ params: { candidateId: "candidate-1" } }),
  useRouter: () => router,
}));

const candidate = {
  version: 1,
  candidateId: "candidate-1",
  orderNo: "E100",
  status: "PENDING",
  validationState: "READY",
  validationIssues: [],
  orderDate: "2026-08-22",
  tracker: "松子",
  trackers: ["松子", "青椒"],
  contractShipDates: ["2026-08-30"], contractShipDate: "2026-08-30",
  category: "帽子",
  totalQuantity: 100,
  shippedQuantity: 0,
  pendingQuantity: 100,
  importedOrderId: null,
  lines: [{ candidateLineId: 1, contractShipDate: "2026-08-30", sourceContractShipDate: "2026-09-03", sourceSkuId: "6970000000001", productName: "测试童帽", propertiesValue: "蓝色 / 120", category: "童帽春夏", factoryName: "测试工厂", orderQuantity: 100, shippedQuantity: 0, pendingQuantity: 100, validationIssues: [] }],
  updatedAt: "2026-08-22T09:00:00",
} satisfies ImportCandidate;

afterEach(() => {
  vi.restoreAllMocks();
  router.push.mockReset();
});

describe("pending order import detail page", () => {
  it("keeps detailed failures at the top but shows only failed in the row cell", async () => {
    vi.spyOn(orderImportApi, "get").mockResolvedValue({
      ...candidate,
      validationState: "INVALID",
      validationIssues: ["FACTORY_NOT_MATCHED"],
      lines: [{ ...candidate.lines[0], validationIssues: ["FACTORY_NOT_MATCHED"] }],
    });
    const wrapper = mount(OrderImportDetailPage, {
      global: { stubs: { AdminShell: { template: "<div><slot /></div>" } } },
    });
    await flushPromises();
    const productTable = wrapper.get(".pending-import-detail-table");
    expect(productTable.findAll("thead th")).toHaveLength(11);
    expect(productTable.findAll("thead th").map((cell) => cell.text())).not.toContain("图片");
    for (const row of productTable.findAll("tbody tr")) {
      expect(row.findAll("td")).toHaveLength(11);
    }


    expect(wrapper.get(".validation-callout").text()).toBe("工厂资料未匹配");
    expect(wrapper.get(".pending-import-detail-table tbody .status-badge").text()).toBe("未通过");
  });

  it("shows the confirmed fields and imports one ready candidate as a draft", async () => {
    vi.spyOn(orderImportApi, "get").mockResolvedValue(candidate);
    vi.spyOn(orderImportApi, "auditLogs").mockResolvedValue({ items: [{ auditId: 1, action: "order_import.detail_updated", targetType: "order_import_candidate", targetId: "candidate-1", changes: { content: "修改订单明细 2 条" }, actorId: "admin-1", operatorName: "煎饼", sourceTerminal: "web_admin", createdAt: "2026-09-15T09:00:00" }], total: 1, page: 1, pageSize: 100, requestId: "audit" });
    const confirm = vi.spyOn(orderImportApi, "confirm").mockResolvedValue({
      orderId: "order-1",
      requestId: "request-1",
    });
    const wrapper = mount(OrderImportDetailPage, {
      global: { stubs: { AdminShell: { template: "<div><slot /></div>" } } },
    });
    await flushPromises();

    expect(wrapper.text()).toContain("合同出货时间");
    expect(wrapper.text()).toContain("测试童帽");
    expect(wrapper.text()).toContain("通过");
    expect(wrapper.findAll(".detail-summary-grid > div")).toHaveLength(6);
    expect(wrapper.findAll(".pending-import-detail-table th")).toHaveLength(11);
    expect(wrapper.findAll(".data-grid-sort-button")).toHaveLength(10);
    expect(wrapper.find(".category-tag").text()).toBe("童帽春夏");
    expect(wrapper.findAll(".tracker-tag").map((item) => item.text())).toEqual(["松子", "青椒"]);
    expect(wrapper.find(".product-thumb").exists()).toBe(false);
    expect(wrapper.get(".detail-code").attributes("title")).toBe("6970000000001");
    expect(wrapper.get(".detail-product-name").attributes("title")).toBe("测试童帽");
    expect(wrapper.find(".detail-progress").text()).toBe("0%");
    const audit = wrapper.get(".pending-import-audit-card").text();
    expect(audit).toContain("煎饼");
    expect(audit).toContain("修改订单明细 2 条");
    expect(audit).toContain("管理员网页");

    await wrapper.get(".detail-primary-button").trigger("click");
    expect(wrapper.text()).toContain("确认将候选订单 E100 导入跟单系统");
    await wrapper.get(".detail-confirm-dialog .detail-primary-button").trigger("click");
    await flushPromises();

    expect(confirm).toHaveBeenCalledWith("candidate-1", 1);
    expect(router.push).toHaveBeenCalledWith({
      path: "/orders/import",
      query: { imported: "E100" },
    });
  });
});


it("saves all changed detail fields together before importing", async () => {
  vi.spyOn(orderImportApi, "get").mockResolvedValue(candidate);
  vi.spyOn(identityApi, "listFactoryOptions").mockResolvedValue({ items: [{ factoryId: "factory-b", factoryName: "测试工厂B", supplierNumber: "FB" }], total: 1 });
  const save = vi.spyOn(orderImportApi, "saveLines").mockRejectedValueOnce(new Error("offline"))
    .mockResolvedValueOnce({ ...candidate, version: 2, contractShipDates: ["2026-09-12"], shippedQuantity: 40, pendingQuantity: 60, lines: [{ ...candidate.lines[0], factoryName: "测试工厂B", contractShipDate: "2026-09-12", shippedQuantity: 40, pendingQuantity: 60 }] });
  const wrapper = mount(OrderImportDetailPage, { global: { stubs: { AdminShell: { template: "<div><slot /></div>" } } } });
  await flushPromises();
  await wrapper.get('input[list="candidate-factory-options"]').setValue("测试工厂B");
  await wrapper.get('input[type="date"]').setValue("2026-09-11");
  const shippedInput = wrapper.get('input[aria-label="6970000000001 已发数量"]');
  const pendingInput = wrapper.get('input[aria-label="6970000000001 未发数量"]');
  await shippedInput.setValue("25");
  expect((pendingInput.element as HTMLInputElement).value).toBe("75");
  await pendingInput.setValue("60");
  expect((shippedInput.element as HTMLInputElement).value).toBe("40");
  const saveButton = wrapper.findAll("button").find((button) => button.text() === "保存")!;
  expect(wrapper.get('.pending-import-detail-actions .detail-primary-button').attributes('disabled')).toBeDefined();
  await saveButton.trigger("click");
  await flushPromises();
  expect(wrapper.get('[role="alert"]').text()).toContain("offline");
  expect((pendingInput.element as HTMLInputElement).value).toBe("60");
  await wrapper.get('input[type="date"]').setValue("2026-09-12");
  await saveButton.trigger("click");
  await flushPromises();
  expect(save).toHaveBeenLastCalledWith("candidate-1", { version: 1, lines: [{ candidateLineId: 1, factoryId: "factory-b", contractShipDate: "2026-09-12", shippedQuantity: 40 }] });
  expect(wrapper.get('.detail-due-date').text()).toBe("2026-09-12");
  expect(wrapper.get('.pending-import-detail-actions .detail-primary-button').attributes('disabled')).toBeUndefined();
});

it("keeps missing dates blank and allows importing", async () => {
  vi.spyOn(orderImportApi, "get").mockResolvedValue({ ...candidate, contractShipDates: [], lines: [{ ...candidate.lines[0], contractShipDate: null }] });
  const confirm = vi.spyOn(orderImportApi, "confirm");
  const wrapper = mount(OrderImportDetailPage, { global: { stubs: { AdminShell: { template: "<div><slot /></div>" } } } });
  await flushPromises();
  expect(wrapper.find('.validation-callout').exists()).toBe(false);
  expect((wrapper.get('input[type="date"]').element as HTMLInputElement).value).toBe("");
  await wrapper.get('.detail-primary-button').trigger('click');
  expect(wrapper.find('[role="alert"]').exists()).toBe(false);
  expect(wrapper.find('[role="dialog"]').exists()).toBe(true);
  expect(confirm).not.toHaveBeenCalled();
});

it("imports incomplete materials with unknown quantities and no contract date", async () => {
  vi.spyOn(orderImportApi, "get").mockResolvedValue({ ...candidate,
    validationState: "INVALID", validationIssues: ["FACTORY_NOT_MATCHED"],
    totalQuantity: null, shippedQuantity: null, pendingQuantity: null,
    lines: [{ ...candidate.lines[0], orderQuantity: null, shippedQuantity: null,
      pendingQuantity: null, contractShipDate: null }],
  });
  const confirm = vi.spyOn(orderImportApi, "confirm").mockResolvedValue({ orderId: "new", requestId: "r" });
  const wrapper = mount(OrderImportDetailPage, { global: { stubs: { AdminShell: { template: "<div><slot /></div>" } } } });
  await flushPromises();
  expect(wrapper.findAll('.detail-summary-number').map(cell => cell.text())).toEqual(["—", "—", "—"]);
  expect(wrapper.get('.detail-progress').text()).toBe("—");
  expect(wrapper.get('.detail-primary-button').attributes('disabled')).toBeUndefined();
  await wrapper.get('.detail-primary-button').trigger('click');
  await wrapper.get('.detail-confirm-dialog .detail-primary-button').trigger('click');
  await flushPromises();
  expect(confirm).toHaveBeenCalledWith("candidate-1", 1);
});
