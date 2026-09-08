import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";

import { orderImportApi, type ImportCandidate } from "@/api/client";
import OrderImportPage from "@/pages/OrderImportPage.vue";

const router = vi.hoisted(() => ({ replace: vi.fn().mockResolvedValue(undefined) }));

vi.mock("vue-router", () => ({
  useRoute: () => ({ query: {} }),
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
  router.replace.mockClear();
});

describe("pending order import page", () => {
  it("shows confirmed filters and only selects ready pending candidates", async () => {
    vi.spyOn(orderImportApi, "latestRun").mockResolvedValue(null);
    const list = vi.spyOn(orderImportApi, "list").mockResolvedValue({ items: [candidate, { ...candidate, candidateId: "candidate-2", orderNo: "E101", validationState: "INVALID", validationIssues: ["FACTORY_NOT_MATCHED"] }], total: 2, page: 1, pageSize: 10, requestId: "request" });
    const wrapper = mount(OrderImportPage, { global: { stubs: { AdminShell: { template: "<div><slot /></div>" }, RouterLink: { template: "<a><slot /></a>" } } } });
    await flushPromises();

    expect(wrapper.text()).toContain("待导入订单");
    expect(wrapper.text()).toContain("获取飞书新订单");
    expect(wrapper.text()).toContain("每页展示 10 条待导入订单");
    expect(wrapper.findAll("tbody input[type=checkbox]")[0].attributes("disabled")).toBeUndefined();
    expect(wrapper.findAll("tbody input[type=checkbox]")[1].attributes("disabled")).toBeDefined();

    await wrapper.get(".import-category-filter").setValue("帽子");
    await wrapper.get(".import-search-form").trigger("submit");
    await flushPromises();
    expect(list).toHaveBeenLastCalledWith(expect.objectContaining({ category: "帽子" }));
  });
});

it("returns to the last valid page after the result count shrinks and updates the URL", async () => {
  vi.spyOn(orderImportApi, "latestRun").mockResolvedValue(null);
  const list = vi.spyOn(orderImportApi, "list").mockResolvedValue({ items: [candidate], total: 200, page: 1, pageSize: 10, requestId: "test" });
  const wrapper = mount(OrderImportPage, { global: { stubs: { AdminShell: { template: "<div><slot/></div>" }, RouterLink: { template: "<a><slot/></a>" } } } });
  await flushPromises();
  list.mockResolvedValueOnce({ items: [], total: 11, page: 20, pageSize: 10, requestId: "test" }).mockResolvedValue({ items: [candidate], total: 11, page: 2, pageSize: 10, requestId: "test" });
  await wrapper.get("button[aria-label='第 20 页']").trigger("click");
  await flushPromises();
  expect(list).toHaveBeenLastCalledWith(expect.objectContaining({ page: 2 }));
  expect(router.replace).toHaveBeenLastCalledWith(expect.objectContaining({ query: expect.objectContaining({ page: "2" }) }));
  expect(wrapper.get("tbody .import-sequence-column").text()).toBe("11");
  wrapper.unmount();
});
