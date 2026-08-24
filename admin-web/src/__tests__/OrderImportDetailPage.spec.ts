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
  candidateId: "candidate-1",
  orderNo: "E100",
  status: "PENDING",
  validationState: "READY",
  validationIssues: [],
  orderDate: "2026-08-22",
  tracker: "松子",
  contractShipDate: "2026-08-30",
  category: "帽子",
  totalQuantity: 100,
  shippedQuantity: 0,
  pendingQuantity: 100,
  importedOrderId: null,
  lines: [{ candidateLineId: 1, sourceSkuId: "6970000000001", productName: "测试童帽", propertiesValue: "蓝色 / 120", category: "童帽春夏", factoryName: "测试工厂", orderQuantity: 100, shippedQuantity: 0, pendingQuantity: 100, validationIssues: [] }],
  updatedAt: "2026-08-22T09:00:00",
} satisfies ImportCandidate;

afterEach(() => {
  vi.restoreAllMocks();
  router.push.mockReset();
});

describe("pending order import detail page", () => {
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
    expect(wrapper.findAll(".data-grid-sort-button")).toHaveLength(9);
    expect(wrapper.find(".category-tag").text()).toBe("帽子");
    expect(wrapper.find(".tracker-tag").text()).toBe("松子");
    expect(wrapper.find(".product-thumb svg").exists()).toBe(true);
    expect(wrapper.find(".detail-progress").text()).toBe("0%");

    await wrapper.get(".detail-primary-button").trigger("click");
    expect(wrapper.text()).toContain("确认将候选订单 E100 导入跟单系统");
    await wrapper.get(".detail-confirm-dialog .detail-primary-button").trigger("click");
    await flushPromises();

    expect(confirm).toHaveBeenCalledWith("candidate-1");
    expect(router.push).toHaveBeenCalledWith({
      path: "/orders/import",
      query: { imported: "E100" },
    });
  });
});
