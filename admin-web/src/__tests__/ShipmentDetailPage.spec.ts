import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, shipmentApi, type Shipment } from "@/api/client";
import ShipmentDetailPage from "@/pages/ShipmentDetailPage.vue";

const routerPush = vi.hoisted(() => vi.fn());
const routeState = vi.hoisted(() => ({ params: { shipmentId: "shipment-1" }, query: {} as Record<string, string | string[]> }));

vi.mock("vue-router", async (importOriginal) => {
  const original = await importOriginal<typeof import("vue-router")>();
  return {
    ...original,
    useRouter: () => ({ push: routerPush }),
    useRoute: () => routeState,
  };
});

const shipment: Shipment = {
  shipmentId: "shipment-1",
  shipmentNo: "FH20260904-001",
  status: "SHIPPED",
  factoryId: "factory-1",
  factoryName: "测试工厂",
  createdBy: "factory-user-1",
  preferredOrderId: null,
  businessDate: "2026-09-04",
  note: "已拍照留档",
  totalBoxes: 1,
  totalQuantity: 2,
  lines: [{ assignmentId: 1, orderId: "order-1", orderNo: "092#", skuId: "SKU-SHIPMENT", itemNumber: "ITEM-SHIPMENT", productName: "测试童帽", propertiesValue: "蓝色 / 52", quantity: 2, lineId: 1, returnedQuantity: 0, returnableQuantity: 2 }],
  boxes: [],
  files: [{
    fileId: 7,
    filename: "proof.png",
    mimeType: "image/png",
    sizeBytes: 68,
    contentSha256: "a".repeat(64),
    displayOrder: 0,
    contentUrl: "/api/v1/shipment-files/7/content",
  }],
  returnEvents: [],
  createdAt: "2026-09-04T08:00:00Z",
  submittedAt: "2026-09-04T08:30:00Z",
  receipt: { status: "CONFIRMED", version: 1, items: [], confirmedByName: null, confirmedAt: "2026-09-04T08:30:00Z" },
};

const shellStub = { template: "<div><slot /></div>" };

it("shows the log window without synthesizing an old submission", async () => {
  vi.spyOn(shipmentApi, "get").mockResolvedValue({ ...shipment, operations: [] });
  const wrapper = mount(ShipmentDetailPage, { global: { stubs: { AdminShell: shellStub, TableSortButton: true } } });
  await flushPromises();
  expect(wrapper.text()).toContain("仅展示最近 30 天的操作记录");
  expect(wrapper.get(".shipment-log-list").text()).toBe("暂无操作记录");
  expect(wrapper.get(".shipment-summary-grid").text()).toContain("发货数量");
});

it("filters only the return log display at the UTC boundary", async () => {
  vi.spyOn(Date, "now").mockReturnValue(Date.parse("2026-10-10T12:00:00Z"));
  const returns = ["2026-09-10T11:59:59", "2026-09-10T20:00:00+08:00"].map((returnedAt, index) => ({
    eventId: `return-${index}`, shipmentId: shipment.shipmentId, returnDate: "2026-09-10",
    reason: `退回原因${index}`, returnedBy: "admin", returnedAt, lines: [],
  }));
  vi.spyOn(shipmentApi, "get").mockResolvedValue({ ...shipment, operations: [], returnEvents: returns });
  const wrapper = mount(ShipmentDetailPage, { global: { stubs: { AdminShell: shellStub, TableSortButton: true } } });
  await flushPromises();
  expect(wrapper.get(".shipment-log-list").text()).not.toContain("退回原因0");
  expect(wrapper.get(".shipment-log-list").text()).toContain("退回原因1");
  expect(returns).toHaveLength(2);
});

beforeEach(() => {
  routeState.query = {};
  vi.spyOn(shipmentApi, "getReceipt").mockResolvedValue({ version: 1, status: "CONFIRMED", items: [], confirmedAt: null, confirmedByName: null });
  vi.spyOn(shipmentApi, "getReceiptOptions").mockResolvedValue({ items: [{ boxItemId: 7, options: [{ assignmentId: 1, orderNo: "092#", productName: "测试童帽", propertiesValue: "蓝色 / 52" }] }] });
});

it("returns to the shipment list with its query context", async () => {
  routeState.query = { keyword: "442", factory: ["工厂甲", "工厂乙"], page: "2" };
  vi.spyOn(shipmentApi, "get").mockResolvedValue(shipment);
  const wrapper = mount(ShipmentDetailPage, { global: { stubs: { AdminShell: shellStub, TableSortButton: true } } });
  await flushPromises();
  await wrapper.get(".detail-back-button").trigger("click");
  expect(routerPush).toHaveBeenCalledWith({ path: "/shipments", query: routeState.query });
});

afterEach(() => {
  vi.restoreAllMocks();
  routerPush.mockReset();
});

describe("shipment evidence in the administrator detail", () => {
  it("renders authenticated evidence with loading and failure states", async () => {
    vi.spyOn(shipmentApi, "get").mockResolvedValue(shipment);
    const wrapper = mount(ShipmentDetailPage, {
      global: {
        stubs: {
          AdminShell: shellStub,
          TableSortButton: { props: ["label"], template: "<span>{{ label }}</span>" },
        },
      },
    });
    await flushPromises();
    const productTable = wrapper.get(".shipment-product-table");
    expect(productTable.findAll("thead th")).toHaveLength(6);
    expect(productTable.findAll("thead th").map((cell) => cell.text())).not.toContain("图片");
    expect(productTable.text()).toContain("货号");
    expect(productTable.text()).toContain("ITEM-SHIPMENT");
    expect(productTable.text()).not.toContain("SKU-SHIPMENT");
    for (const row of productTable.findAll("tbody tr")) {
      expect(row.findAll("td")).toHaveLength(6);
    }


    expect(wrapper.text()).toContain("发货凭证（1 张）");
    expect(wrapper.text()).toContain("凭证加载中…");
    expect(wrapper.get("img.shipment-proof-image").attributes("src")).toBe(
      "/api/v1/shipment-files/7/content",
    );

    await wrapper.get("img.shipment-proof-image").trigger("load");
    expect(wrapper.text()).not.toContain("凭证加载中…");
    await wrapper.get("img.shipment-proof-image").trigger("error");
    expect(wrapper.text()).toContain("凭证加载失败");
  });

  it("keeps the approved empty placeholder when no evidence exists", async () => {
    vi.spyOn(shipmentApi, "get").mockResolvedValue({ ...shipment, files: [] });
    const wrapper = mount(ShipmentDetailPage, {
      global: { stubs: { AdminShell: shellStub, TableSortButton: true } },
    });
    await flushPromises();

    expect(wrapper.text()).toContain("发货凭证（0 张）");
    expect(wrapper.text()).toContain("工厂未上传发货凭证");
  });
});


describe("receipt verification", () => {
  it("keeps shipment details and allows retry when packing data initially fails", async () => {
    vi.spyOn(shipmentApi, "get").mockResolvedValue(shipment);
    vi.mocked(shipmentApi.getReceipt).mockRejectedValueOnce(new Error("offline"));
    const wrapper = mount(ShipmentDetailPage, { global: { stubs: { AdminShell: shellStub, TableSortButton: true } } });
    await flushPromises();
    expect(wrapper.get(".shipment-product-table").text()).toContain("测试童帽");
    expect(wrapper.get('[data-action="save-receipt"]').attributes("disabled")).toBeDefined();
    await wrapper.get('[role="alert"] button').trigger("click");
    await flushPromises();
    expect(wrapper.find('[data-action="save-receipt"]').exists()).toBe(true);
    expect(shipmentApi.getReceipt).toHaveBeenCalledTimes(2);
  });

  it("saves a selected specification from another order of the same product", async () => {
    const value = { ...shipment, boxes: [{ boxNo: 1, groupKey: null, items: [{ ...shipment.lines[0]!, boxItemId: 7 }] }] };
    vi.spyOn(shipmentApi, "get").mockResolvedValue(value);
    vi.mocked(shipmentApi.getReceipt).mockResolvedValueOnce({ version: 1, status: "CONFIRMED", items: [{ boxItemId: 7, quantity: 2, assignmentId: 1 }] })
      .mockResolvedValue({ version: 2, status: "CONFIRMED", items: [{ boxItemId: 7, quantity: 2, assignmentId: 2 }] });
    vi.mocked(shipmentApi.getReceiptOptions).mockResolvedValue({ items: [{ boxItemId: 7, options: [
      { assignmentId: 1, orderNo: "092#", productName: "测试童帽", propertiesValue: "蓝色 / 52" },
      { assignmentId: 2, orderNo: "093#", productName: "测试童帽", propertiesValue: "白色 / 52" },
    ] }] });
    const save = vi.spyOn(shipmentApi, "saveReceipt").mockResolvedValue({ version: 2, status: "CONFIRMED", items: [{ boxItemId: 7, quantity: 2, assignmentId: 2 }] });
    const wrapper = mount(ShipmentDetailPage, { global: { stubs: { AdminShell: shellStub, TableSortButton: true } } });
    await flushPromises();
    await wrapper.get('select[aria-label="箱号 1 ITEM-SHIPMENT 颜色规格"]').setValue("2");
    expect(wrapper.get(".shipment-summary-grid dd").text()).toBe("093#");
    expect(wrapper.get(".packing-detail-table tbody").text()).toContain("093#");
    expect(wrapper.get(".shipment-product-table tbody").text()).toContain("白色 / 52");
    await wrapper.get('[data-action="save-receipt"]').trigger("click");
    await flushPromises();
    expect(save).toHaveBeenCalledWith("shipment-1", 1, [{ boxItemId: 7, quantity: 2, assignmentId: 2 }], expect.any(String));
    expect(wrapper.text()).toContain("订单发货数量已同步");
    expect(wrapper.find('[data-action="save-receipt"]').exists()).toBe(true);
  });

  it("shows the withdrawn history without receipt or approval actions", async () => {
    vi.spyOn(shipmentApi, "get").mockResolvedValue({ ...shipment, status: "WITHDRAWN",
      operations: [{action:"shipment_withdrawn",reason:"数量录错",actorName:"乙",createdAt:"2026-09-09T03:00:00Z"}] });
    const wrapper = mount(ShipmentDetailPage, {global:{stubs:{AdminShell:shellStub,TableSortButton:true}}});
    await flushPromises();
    expect(wrapper.text()).toContain("已撤回");
    expect(wrapper.text()).toContain("数量录错");
    expect(wrapper.find('[data-action="confirm-receipt"]').exists()).toBe(false);
    expect(wrapper.find('[data-action="save-receipt"]').exists()).toBe(false);
    expect(wrapper.text()).not.toContain("通过撤回申请");
    expect(shipmentApi.getReceipt).not.toHaveBeenCalled();
  });

  it("preserves unsaved quantities on conflict until explicitly reloaded", async () => {
    const value = { ...shipment, boxes: [{ boxNo: 1, groupKey: null, items: [{ ...shipment.lines[0]!, boxItemId: 7 }] }] };
    vi.spyOn(shipmentApi, "get").mockResolvedValueOnce(value).mockResolvedValue({...shipment,status:"WITHDRAWN"});
    vi.mocked(shipmentApi.getReceipt).mockResolvedValue({ version: 1, status: "CONFIRMED", items: [{ boxItemId: 7, quantity: 2, assignmentId: 1 }] });
    vi.spyOn(shipmentApi, "saveReceipt").mockRejectedValue(new ApiError(409, "conflict", "发货单已撤回"));
    const wrapper = mount(ShipmentDetailPage, {global:{stubs:{AdminShell:shellStub,TableSortButton:true}}});
    await flushPromises();
    await wrapper.get('input[type="number"]').setValue("9");
    await wrapper.get('[data-action="save-receipt"]').trigger("click");
    await flushPromises();
    expect(wrapper.text()).toContain("发货单已撤回");
    expect((wrapper.get('input[type="number"]').element as HTMLInputElement).value).toBe("9");
    expect(shipmentApi.get).toHaveBeenCalledTimes(1);
    await wrapper.get('[role="alert"] button').trigger("click");
    await flushPromises();
    expect(wrapper.find('[data-action="save-receipt"]').exists()).toBe(false);
    expect(wrapper.find('[data-action="confirm-receipt"]').exists()).toBe(false);
  });

  it("retries an unknown save with the same key and keeps received packing editable", async () => {
    const value = { ...shipment, boxes: [{ boxNo: 1, groupKey: null, items: [{ ...shipment.lines[0]!, boxItemId: 7 }] }] };
    vi.spyOn(shipmentApi, "get").mockResolvedValue(value);
    vi.mocked(shipmentApi.getReceipt).mockResolvedValueOnce({ version: 1, status: "CONFIRMED", items: [{ boxItemId: 7, quantity: 2, assignmentId: 1 }] })
      .mockResolvedValue({ version: 2, status: "CONFIRMED", items: [{ boxItemId: 7, quantity: 0, assignmentId: 1 }] });
    const save = vi.spyOn(shipmentApi, "saveReceipt").mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValue({ version: 2, status: "CONFIRMED", items: [{ boxItemId: 7, quantity: 0, assignmentId: 1 }] });
    const wrapper = mount(ShipmentDetailPage, { global: { stubs: { AdminShell: shellStub, TableSortButton: true } } });
    await flushPromises();
    await wrapper.get('input[aria-label="箱号 1 ITEM-SHIPMENT 核对数量"]').setValue("0");
    expect(wrapper.get(".shipment-product-table tbody tr td:last-child").text()).toBe("0");
    expect(wrapper.find('[data-action="confirm-receipt"]').exists()).toBe(false);
    await wrapper.get('[data-action="save-receipt"]').trigger("click");
    await flushPromises();
    await wrapper.get('[data-action="save-receipt"]').trigger("click");
    await flushPromises();
    expect(save).toHaveBeenCalledTimes(2);
    expect(save.mock.calls[0]).toEqual(save.mock.calls[1]);
    expect(wrapper.text()).toContain("已收货");
    expect(wrapper.find('input[type="number"]').exists()).toBe(true);
    expect((wrapper.get('input[type="number"]').element as HTMLInputElement).value).toBe("0");
    expect(wrapper.find('[data-action="confirm-receipt"]').exists()).toBe(false);
  });
});

it("uses the item number in shipment lines, boxes and the return dialog", async () => {
  vi.spyOn(shipmentApi, "get").mockResolvedValue({
    ...shipment,
    boxes: [{ boxNo: 1, groupKey: null, items: [{ ...shipment.lines[0]!, boxItemId: 7 }] }],
  });
  const wrapper = mount(ShipmentDetailPage, { global: { stubs: { AdminShell: shellStub } } });
  await flushPromises();

  expect(wrapper.get(".shipment-product-table").text()).toContain("货号");
  expect(wrapper.get(".packing-detail-table").text()).toContain("货号");
  expect(wrapper.get(".packing-detail-table").text()).toContain("ITEM-SHIPMENT");
  expect(wrapper.get(".packing-detail-table").text()).not.toContain("SKU-SHIPMENT");

  await wrapper.findAll("button").find((button) => button.text() === "退回")!.trigger("click");
  expect(wrapper.get(".shipment-return-table").text()).toContain("货号");
  expect(wrapper.get(".shipment-return-table").text()).toContain("ITEM-SHIPMENT");
  expect(wrapper.get(".shipment-return-table").text()).not.toContain("SKU-SHIPMENT");
});
