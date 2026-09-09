import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, shipmentApi, type Shipment } from "@/api/client";
import ShipmentDetailPage from "@/pages/ShipmentDetailPage.vue";

const routerPush = vi.hoisted(() => vi.fn());

vi.mock("vue-router", async (importOriginal) => {
  const original = await importOriginal<typeof import("vue-router")>();
  return {
    ...original,
    useRouter: () => ({ push: routerPush }),
    useRoute: () => ({ params: { shipmentId: "shipment-1" }, query: {} }),
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
  lines: [{ assignmentId: 1, orderId: "order-1", orderNo: "092#", skuId: "KQ26721", productName: "测试童帽", propertiesValue: "蓝色 / 52", quantity: 2, lineId: 1, returnedQuantity: 0, returnableQuantity: 2 }],
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
  vi.spyOn(shipmentApi, "getReceipt").mockResolvedValue({ version: 0, status: "DRAFT", items: [], confirmedAt: null, confirmedByName: null });
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
          TableSortButton: { template: "<span />" },
        },
      },
    });
    await flushPromises();
    const productTable = wrapper.get(".shipment-product-table");
    expect(productTable.findAll("thead th")).toHaveLength(6);
    expect(productTable.findAll("thead th").map((cell) => cell.text())).not.toContain("图片");
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
    vi.mocked(shipmentApi.getReceipt).mockResolvedValue({ version: 0, status: "DRAFT", items: [{ boxItemId: 7, quantity: 2 }], confirmedAt: null, confirmedByName: null });
    const save = vi.spyOn(shipmentApi, "saveReceipt").mockResolvedValue({ version: 1, status: "DRAFT", items: [{ boxItemId: 7, quantity: 0 }], confirmedAt: null, confirmedByName: null });
    const confirm = vi.spyOn(shipmentApi, "confirmReceipt").mockResolvedValue({ ...value, totalQuantity: 0, receipt: { version: 1, status: "CONFIRMED", items: [{ boxItemId: 7, quantity: 0 }], confirmedAt: "2026-09-07T02:00:00", confirmedByName: "核对员" }, lines: [{ ...value.lines[0]!, quantity: 0 }], boxes: [{ ...value.boxes[0]!, items: [{ ...value.boxes[0]!.items[0]!, quantity: 0 }] }] });
    const wrapper = mount(ShipmentDetailPage, { global: { stubs: { AdminShell: shellStub, TableSortButton: true } } });
    await flushPromises();
    await wrapper.get('input[aria-label="箱号 1 KQ26721 核对数量"]').setValue("0");
    expect(wrapper.get(".shipment-product-table tbody tr td:last-child").text()).toBe("0");
    await wrapper.get('[data-action="confirm-receipt"]').trigger("click");
    expect(wrapper.text()).toContain("请先保存");
    expect(confirm).not.toHaveBeenCalled();
    await wrapper.get('[data-action="save-receipt"]').trigger("click");
    await flushPromises();
    expect(save).toHaveBeenCalledWith("shipment-1", 0, [{ boxItemId: 7, quantity: 0 }]);
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
