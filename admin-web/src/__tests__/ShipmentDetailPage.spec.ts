import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";

import { shipmentApi, type Shipment } from "@/api/client";
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
  lines: [],
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
