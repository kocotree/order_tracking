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
  voidRequest: null,
  returnEvents: [],
  createdAt: "2026-09-04T08:00:00Z",
  submittedAt: "2026-09-04T08:30:00Z",
};

const shellStub = { template: "<div><slot /></div>" };

beforeEach(() => {
  routeState.query = {};
  vi.spyOn(shipmentApi, "getReceipt").mockResolvedValue({ version: 0, status: "DRAFT", items: [], confirmedAt: null, confirmedByName: null });
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
  it("saves a selected specification from another order of the same product", async () => {
    const value = { ...shipment, boxes: [{ boxNo: 1, groupKey: null, items: [{ ...shipment.lines[0]!, boxItemId: 7 }] }] };
    vi.spyOn(shipmentApi, "get").mockResolvedValue(value);
    vi.mocked(shipmentApi.getReceipt).mockResolvedValue({ version: 0, status: "DRAFT", items: [{ boxItemId: 7, quantity: 2, assignmentId: 1 }] });
    vi.mocked(shipmentApi.getReceiptOptions).mockResolvedValue({ items: [{ boxItemId: 7, options: [
      { assignmentId: 1, orderNo: "092#", productName: "测试童帽", propertiesValue: "蓝色 / 52" },
      { assignmentId: 2, orderNo: "093#", productName: "测试童帽", propertiesValue: "白色 / 52" },
    ] }] });
    const save = vi.spyOn(shipmentApi, "saveReceipt").mockResolvedValue({ version: 1, status: "DRAFT", items: [{ boxItemId: 7, quantity: 2, assignmentId: 2 }] });
    const wrapper = mount(ShipmentDetailPage, { global: { stubs: { AdminShell: shellStub, TableSortButton: true } } });
    await flushPromises();
    await wrapper.get('select[aria-label="箱号 1 ITEM-SHIPMENT 颜色规格"]').setValue("2");
    expect(wrapper.get(".shipment-summary-grid dd").text()).toBe("093#");
    expect(wrapper.get(".packing-detail-table tbody").text()).toContain("093#");
    expect(wrapper.get(".shipment-product-table tbody").text()).toContain("白色 / 52");
    await wrapper.get('[data-action="save-receipt"]').trigger("click");
    await flushPromises();
    expect(save).toHaveBeenCalledWith("shipment-1", 0, [{ boxItemId: 7, quantity: 2, assignmentId: 2 }]);
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

  it("refreshes a stale receipt page to read-only after withdrawal", async () => {
    vi.spyOn(shipmentApi, "get").mockResolvedValueOnce(shipment)
      .mockResolvedValue({...shipment,status:"WITHDRAWN"});
    vi.spyOn(shipmentApi, "saveReceipt").mockRejectedValue(new ApiError(409, "conflict", "发货单已撤回"));
    const wrapper = mount(ShipmentDetailPage, {global:{stubs:{AdminShell:shellStub,TableSortButton:true}}});
    await flushPromises();
    await wrapper.get('[data-action="save-receipt"]').trigger("click");
    await flushPromises();
    expect(wrapper.text()).toContain("发货单已撤回");
    expect(wrapper.find('[data-action="save-receipt"]').exists()).toBe(false);
    expect(wrapper.find('[data-action="confirm-receipt"]').exists()).toBe(false);
  });

  it("saves by box, derives totals, requires save before confirm and locks confirmed values", async () => {
    const value = { ...shipment, boxes: [{ boxNo: 1, groupKey: null, items: [{ ...shipment.lines[0]!, boxItemId: 7 }] }] };
    vi.spyOn(shipmentApi, "get").mockResolvedValue(value);
    vi.mocked(shipmentApi.getReceipt).mockResolvedValue({ version: 0, status: "DRAFT", items: [{ boxItemId: 7, quantity: 2, assignmentId: 1 }], confirmedAt: null, confirmedByName: null });
    const save = vi.spyOn(shipmentApi, "saveReceipt").mockResolvedValue({ version: 1, status: "DRAFT", items: [{ boxItemId: 7, quantity: 0, assignmentId: 1 }], confirmedAt: null, confirmedByName: null });
    const confirm = vi.spyOn(shipmentApi, "confirmReceipt").mockResolvedValue({ ...value, totalQuantity: 0, receipt: { version: 1, status: "CONFIRMED", items: [{ boxItemId: 7, quantity: 0, assignmentId: 1 }], confirmedAt: "2026-09-07T02:00:00", confirmedByName: "核对员" }, lines: [{ ...value.lines[0]!, quantity: 0 }], boxes: [{ ...value.boxes[0]!, items: [{ ...value.boxes[0]!.items[0]!, quantity: 0 }] }] });
    const wrapper = mount(ShipmentDetailPage, { global: { stubs: { AdminShell: shellStub, TableSortButton: true } } });
    await flushPromises();
    await wrapper.get('input[aria-label="箱号 1 ITEM-SHIPMENT 核对数量"]').setValue("0");
    expect(wrapper.get(".shipment-product-table tbody tr td:last-child").text()).toBe("0");
    await wrapper.get('[data-action="confirm-receipt"]').trigger("click");
    expect(wrapper.text()).toContain("请先保存");
    expect(confirm).not.toHaveBeenCalled();
    await wrapper.get('[data-action="save-receipt"]').trigger("click");
    await flushPromises();
    expect(save).toHaveBeenCalledWith("shipment-1", 0, [{ boxItemId: 7, quantity: 0, assignmentId: 1 }]);
    await wrapper.get('[data-action="confirm-receipt"]').trigger("click");
    await flushPromises();
    expect(confirm).toHaveBeenCalledWith("shipment-1", 1);
    expect(wrapper.text()).toContain("已收货");
    expect(wrapper.text()).toContain("核对员");
    expect(wrapper.text()).not.toContain("收货已确认");
    expect(wrapper.find('[role="status"]').exists()).toBe(false);
    expect(wrapper.find('input[type="number"]').exists()).toBe(false);
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
