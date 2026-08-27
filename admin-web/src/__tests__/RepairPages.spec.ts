import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";

import { repairApi, type Repair, type RepairPreview } from "@/api/client";
import RepairCreatePage from "@/pages/RepairCreatePage.vue";
import RepairDetailPage from "@/pages/RepairDetailPage.vue";
import RepairsPage from "@/pages/RepairsPage.vue";

const routerPush = vi.hoisted(() => vi.fn());
const routeParams = vi.hoisted(() => ({ repairId: "repair-1" }));

vi.mock("vue-router", async (importOriginal) => {
  const original = await importOriginal<typeof import("vue-router")>();
  return {
    ...original,
    useRouter: () => ({ push: routerPush, replace: routerPush }),
    useRoute: () => ({ params: routeParams }),
  };
});

const repair: Repair = {
  repairId: "repair-1",
  repairNo: "FX20260826-001",
  status: "INCOMPLETE",
  returnDate: "2026-08-26",
  factoryId: "factory-1",
  factoryName: "宇婷",
  warehouseReturnQuantity: 826,
  repairedQuantity: 0,
  scrappedQuantity: 0,
  returnedQuantity: 0,
  originalFileId: 1,
  originalFilename: "E22质检.xlsx",
  originalSizeBytes: 1_600_000,
  createdAt: "2026-08-26T12:00:00",
  specs: [],
  returnBatches: [],
  lines: [{
    inspectionLineId: 1,
    sourceRow: 2,
    sourceOrder: 1,
    boxNumber: "1号箱",
    productId: "product-1",
    variantId: "variant-1",
    sourceSkuId: "6941716530266",
    sourceProductId: "KQ26001",
    productName: "夏宠冰果乐披风帽",
    propertiesValue: "椰椰西瓜冻L",
    warehouseReturnQuantity: 18,
    reason: "面料次",
  }],
};

const preview: RepairPreview = {
  previewId: "preview-1",
  status: "READY",
  expiresAt: "2026-08-27T12:00:00",
  originalFileId: 1,
  originalFilename: "E22质检.xlsx",
  factoryId: "factory-1",
  factoryName: "宇婷",
  lineCount: 1,
  boxCount: 1,
  totalQuantity: 18,
  validationErrors: [],
  lines: [{
    lineId: 1,
    sourceRow: 2,
    sourceOrder: 1,
    sourceSkuId: "6941716530266",
    sourceProductId: "KQ26001",
    productName: "夏宠冰果乐披风帽",
    propertiesValue: "椰椰西瓜冻L",
    quantity: 18,
    boxNumber: "1号箱",
    reason: "面料次",
    matchedProductId: "product-1",
    matchedVariantId: "variant-1",
  }],
};

const shellStub = { template: "<div><slot /></div>" };

afterEach(() => {
  vi.restoreAllMocks();
  routerPush.mockReset();
});

describe("repair web prototype alignment", () => {
  it("renders the prototype list density and eight sortable business columns", async () => {
    vi.spyOn(repairApi, "list").mockResolvedValue({ items: [repair], total: 1, page: 1, pageSize: 10 });
    const wrapper = mount(RepairsPage, { global: { stubs: { AdminShell: shellStub } } });
    await flushPromises();

    expect(wrapper.findAll(".data-grid-sort-button")).toHaveLength(8);
    expect(wrapper.find(".repair-filter-row .order-list-search-field").exists()).toBe(true);
    expect(wrapper.get(".repair-list-table .status-badge").classes()).toContain("is-info");
    expect(wrapper.get(".repair-list-footer").text()).toContain("每页展示 10 条返修单");
  });

  it("offers archive only for completed repairs and archives after confirmation", async () => {
    const completed = {
      ...repair,
      repairId: "repair-2",
      repairNo: "FX20260826-002",
      status: "COMPLETED" as const,
      repairedQuantity: 826,
      returnedQuantity: 826,
    };
    vi.spyOn(repairApi, "list").mockResolvedValue({ items: [repair, completed], total: 2, page: 1, pageSize: 10 });
    const archive = vi.spyOn(repairApi, "archive").mockResolvedValue({ repairId: completed.repairId, archivedAt: "2026-08-27T12:00:00", archivedBy: "admin-1" });
    const wrapper = mount(RepairsPage, { global: { stubs: { AdminShell: shellStub } } });
    await flushPromises();

    expect(wrapper.findAll(".repair-archive-button")).toHaveLength(1);
    await wrapper.get(".repair-archive-button").trigger("click");
    expect(wrapper.get("[role=dialog]").text()).toContain("FX20260826-002");
    await wrapper.get("[data-repair-archive-confirm]").trigger("click");
    await flushPromises();

    expect(archive).toHaveBeenCalledWith("repair-2");
    expect(wrapper.text()).not.toContain("FX20260826-002");
  });

  it("uses the compact detail matrix and omits photo parsing UI", async () => {
    vi.spyOn(repairApi, "get").mockResolvedValue({
      ...repair,
      lines: [
        repair.lines[0],
        {
          ...repair.lines[0],
          inspectionLineId: 2,
          sourceRow: 3,
          sourceOrder: 2,
          boxNumber: "2号箱",
          warehouseReturnQuantity: 24,
        },
      ],
    });
    const wrapper = mount(RepairDetailPage, { global: { stubs: { AdminShell: shellStub } } });
    await flushPromises();

    expect(wrapper.findAll(".repair-summary-matrix dt")).toHaveLength(4);
    expect(wrapper.findAll(".repair-quality-table th")).toHaveLength(7);
    expect(wrapper.find(".repair-detail-title .status-badge").exists()).toBe(false);
    expect(wrapper.findAll(".repair-reason-cell")).toHaveLength(1);
    expect(wrapper.get(".repair-reason-cell").attributes("rowspan")).toBe("2");
    expect(wrapper.text()).not.toContain("次品照片");
    expect(wrapper.text()).not.toContain("补传");
    expect(wrapper.get(".repair-source-file").text()).toContain("2 个箱号 · 2 条明细 · 仓库退回 826 件");
  });

  it("renders real factory return batch lines in the eight-column detail table", async () => {
    vi.spyOn(repairApi, "get").mockResolvedValue({
      ...repair,
      repairedQuantity: 5,
      returnedQuantity: 5,
      returnBatches: [{
        batchId: "batch-1",
        submittedAt: "2026-08-27T03:00:00",
        returnDate: "2026-08-27",
        submittedBy: "factory-user-1",
        lines: [{
          variantId: "variant-1",
          sourceSkuId: "6941716530266",
          sourceProductId: "KQ26001",
          productName: "夏宠冰果乐披风帽",
          propertiesValue: "椰椰西瓜冻L",
          warehouseReturnQuantity: 18,
          repairedQuantity: 5,
          scrappedQuantity: 0,
          returnedQuantity: 5,
        }],
      }],
    });
    const wrapper = mount(RepairDetailPage, { global: { stubs: { AdminShell: shellStub } } });
    await flushPromises();

    expect(wrapper.findAll(".repair-return-table th")).toHaveLength(8);
    expect(wrapper.findAll(".repair-return-table tbody tr")).toHaveLength(1);
    expect(wrapper.get(".repair-return-table tbody").text()).toContain("2026-08-27");
    expect(wrapper.get(".repair-return-table tbody").text()).toContain("椰椰西瓜冻L");
    expect(wrapper.text()).not.toContain("工厂尚未提交返修发回记录");
  });

  it("previews structured Excel fields without photo upload controls", async () => {
    vi.spyOn(repairApi, "upload").mockResolvedValue(preview);
    const wrapper = mount(RepairCreatePage, { global: { stubs: { AdminShell: shellStub } } });
    const input = wrapper.get<HTMLInputElement>('input[type="file"]');
    Object.defineProperty(input.element, "files", { value: [new File(["xlsx"], "E22质检.xlsx")] });
    await input.trigger("change");
    await flushPromises();

    expect(wrapper.findAll(".repair-preview-table th")).toHaveLength(7);
    expect(wrapper.text()).not.toContain("次品照片");
    expect(wrapper.text()).not.toContain("补传");
  });
});
