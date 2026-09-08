import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";

import { orderImportApi, type ImportCandidate } from "@/api/client";
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
    expect(wrapper.find(".category-tag").text()).toBe("帽子");
    expect(wrapper.find(".tracker-tag").text()).toBe("松子");
    expect(wrapper.find(".product-thumb").exists()).toBe(false);
    expect(wrapper.get(".detail-code").attributes("title")).toBe("6970000000001");
    expect(wrapper.get(".detail-product-name").attributes("title")).toBe("测试童帽");
    expect(wrapper.find(".detail-progress").text()).toBe("0%");

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


it("saves detail dates before importing and surfaces failures", async () => {
  vi.spyOn(orderImportApi, "get").mockResolvedValue(candidate);
  const save = vi.spyOn(orderImportApi, "saveDate").mockRejectedValueOnce(new Error("offline"))
    .mockResolvedValueOnce({ ...candidate, version: 2, contractShipDates: ["2026-09-12"], lines: [{ ...candidate.lines[0], contractShipDate: "2026-09-12" }] });
  const wrapper = mount(OrderImportDetailPage, { global: { stubs: { AdminShell: { template: "<div><slot /></div>" } } } });
  await flushPromises();
  await wrapper.get('input[type="date"]').setValue("2026-09-11");
  await flushPromises();
  expect(wrapper.get('[role="alert"]').text()).toContain("日期保存失败");
  expect(wrapper.get('.detail-primary-button').attributes('disabled')).toBeDefined();
  await wrapper.get('input[type="date"]').setValue("2026-09-12");
  await flushPromises();
  expect(save).toHaveBeenLastCalledWith("candidate-1", 1, 1, "2026-09-12");
  expect(wrapper.get('.detail-due-date').text()).toBe("2026-09-12");
  expect(wrapper.get('.detail-primary-button').attributes('disabled')).toBeUndefined();
});

it("keeps missing dates blank and locates the row when importing", async () => {
  vi.spyOn(orderImportApi, "get").mockResolvedValue({ ...candidate, contractShipDates: [], lines: [{ ...candidate.lines[0], contractShipDate: null }] });
  const confirm = vi.spyOn(orderImportApi, "confirm");
  const wrapper = mount(OrderImportDetailPage, { global: { stubs: { AdminShell: { template: "<div><slot /></div>" } } } });
  await flushPromises();
  expect(wrapper.find('.validation-callout').exists()).toBe(false);
  expect((wrapper.get('input[type="date"]').element as HTMLInputElement).value).toBe("");
  await wrapper.get('.detail-primary-button').trigger('click');
  expect(wrapper.get('[role="alert"]').text()).toContain("6970000000001");
  expect(wrapper.find('[role="dialog"]').exists()).toBe(false);
  expect(confirm).not.toHaveBeenCalled();
});
