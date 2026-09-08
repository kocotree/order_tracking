import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, expect, it, vi } from "vitest";
import { identityApi, orderApi, type Order } from "@/api/client";
import OrderFormPage from "@/pages/OrderFormPage.vue";

const router = vi.hoisted(() => ({ replace: vi.fn(), back: vi.fn() }));
vi.mock("vue-router", () => ({ useRoute: () => ({ params: { orderId: "draft" } }), useRouter: () => router }));
afterEach(() => vi.restoreAllMocks());
it("edits each factory date and saves it without a whole-order date", async () => {
  const order: Order = {
    requestId: "test", orderId: "draft", orderNo: "DATE-1", orderDate: null, source: "feishu", tracker: "松子",
    contractShipDate: "2026-09-10", contractShipDates: ["2026-09-10", "2026-09-20"],
    lifecycle: "DRAFT", displayStatus: "草稿", version: 3, totalQuantity: 100,
    shippedQuantity: 0, pendingQuantity: 100, overQuantity: 0, shortQuantity: 100, progressPercent: 0,
    lines: [{ orderLineId: 1, variantId: "sku", skuId: "SKU", productName: "帽子", propertiesValue: "蓝色",
      category: "童帽春夏", imageObjectKey: null, orderQuantity: 100, shippedQuantity: 0, pendingQuantity: 100,
      overQuantity: 0, shortQuantity: 100, progressPercent: 0, assignments: [
        { assignmentId: 1, factoryId: "a", factoryName: "甲", assignedQuantity: 40, shippedQuantity: 0, pendingQuantity: 40, overQuantity: 0, shortQuantity: 40, progressPercent: 0, contractShipDate: "2026-09-10" },
        { assignmentId: 2, factoryId: "b", factoryName: "乙", assignedQuantity: 60, shippedQuantity: 0, pendingQuantity: 60, overQuantity: 0, shortQuantity: 60, progressPercent: 0, contractShipDate: "2026-09-20" },
      ] }], factoryProgress: [], validationIssues: [], createdAt: "2026-09-01", updatedAt: "2026-09-01",
  };
  vi.spyOn(orderApi, "get").mockResolvedValue(order);
  vi.spyOn(identityApi, "listProducts").mockResolvedValue({ items: [], total: 0, page: 1, pageSize: 100 });
  vi.spyOn(identityApi, "listFactories").mockResolvedValue({ items: [], total: 0 });
  const save = vi.spyOn(orderApi, "saveDraft").mockResolvedValue(order);
  const wrapper = mount(OrderFormPage, { global: { stubs: { AdminShell: { template: "<div><slot /></div>" } } } });
  await flushPromises();
  const dates = wrapper.findAll('.assignment-row input[type="date"]');
  expect(dates).toHaveLength(2);
  await dates[0]!.setValue("2026-09-12");
  expect(wrapper.get('.date-summary').text()).toBe("2026-09-12、2026-09-20");
  await wrapper.get('form').trigger('submit');
  await flushPromises();
  expect(save).toHaveBeenCalledWith("draft", expect.objectContaining({ version: 3, lines: [{ variantId: "sku", orderQuantity: 100, assignments: [{ factoryId: "a", quantity: 40, contractShipDate: "2026-09-12" }, { factoryId: "b", quantity: 60, contractShipDate: "2026-09-20" }] }] }));
  expect(save.mock.calls[0]![1]).not.toHaveProperty("contractShipDate");
});
