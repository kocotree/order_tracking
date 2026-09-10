import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, repairApi, type Repair, type RepairPreview } from "@/api/client";
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

beforeEach(() => { vi.spyOn(repairApi,"listPeriodOptions").mockResolvedValue({items:["2026.8-2027.1"]}); vi.spyOn(repairApi, "listFactoryOptions").mockResolvedValue({items:["宇婷","阿厂2"]}); });

afterEach(() => {
  vi.restoreAllMocks();
  routerPush.mockReset();
});

describe("repair web prototype alignment", () => {
  it("renders the prototype list density and eight sortable business columns", async () => {
    vi.spyOn(repairApi, "listSummaries").mockResolvedValue({ items: [repair], total: 1, page: 1, pageSize: 10 });
    const wrapper = mount(RepairsPage, { global: { stubs: { AdminShell: shellStub } } });
    await flushPromises();

    expect(wrapper.findAll(".data-grid-sort-button")).toHaveLength(7);
    expect(wrapper.find(".repair-filter-row .order-list-search-field").exists()).toBe(true);
    expect(wrapper.get(".repair-list-table .status-badge").classes()).toContain("is-info");
    expect(wrapper.get(".repair-list-footer").text()).toContain("每页展示 10 条返修周期");
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
    vi.spyOn(repairApi, "listSummaries").mockResolvedValueOnce({ items: [repair, completed], total: 2, page: 1, pageSize: 10 }).mockResolvedValue({items:[repair], total:1, page:1, pageSize:10});
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

  it("shows all period attachments and SKU totals, without inspection boxes or return history", async () => {
    vi.spyOn(repairApi,"get").mockResolvedValue({...repair,repairNo:"2026.8-2027.1",attachments:[{fileId:1,filename:"2026-09-09-01.xlsx",sizeBytes:50},{fileId:2,filename:"2026-09-09-02.xlsx",sizeBytes:50}],specs:[{variantId:"v",sourceSkuId:"SKU1",sourceProductId:"P1",productName:"演示帽",propertiesValue:"蓝色",warehouseReturnQuantity:50,repairedQuantity:35,scrappedQuantity:5,returnedQuantity:40,pendingQuantity:10}]});
    const download=vi.spyOn(repairApi,"download").mockResolvedValue();
    const wrapper=mount(RepairDetailPage,{global:{stubs:{AdminShell:shellStub}}});
    await flushPromises();
    expect(wrapper.findAll(".repair-summary-matrix dt")).toHaveLength(4);
    expect(wrapper.findAll(".repair-source-file")).toHaveLength(2);
    expect(wrapper.findAll(".repair-product-table th")).toHaveLength(8);
    expect(wrapper.get(".repair-product-table").text()).toContain("40 / 50");
    expect(wrapper.get(".repair-product-table").text()).toContain("80%");
    expect(wrapper.text()).not.toContain("工厂发回记录");
    expect(wrapper.text()).not.toContain("箱号");
    await wrapper.findAll(".repair-source-file button")[1]!.trigger('click');
    expect(download).toHaveBeenCalledWith(2,"2026-09-09-02.xlsx");
    wrapper.unmount();
  });

  it("shows the original filename and parse state without inspection details", async () => {
    vi.spyOn(repairApi, "upload").mockResolvedValue(preview);
    const wrapper = mount(RepairCreatePage, { global: { stubs: { AdminShell: shellStub } } });
    const input = wrapper.get<HTMLInputElement>('input[type="file"]');
    Object.defineProperty(input.element, "files", { value: [new File(["xlsx"], "E22质检.xlsx")] });
    await input.trigger("change");
    await flushPromises();

    expect(wrapper.find("table").exists()).toBe(false);
    expect(wrapper.text()).toContain("E22质检.xlsx");
    expect(wrapper.text()).toContain("解析通过，等待确认");
    expect(wrapper.text()).not.toContain("次品照片");
    expect(wrapper.text()).not.toContain("补传");
  });
});

it("loads repairs beyond the first hundred and returns from an emptied last page", async () => {
  const rows = Array.from({ length: 101 }, (_, index) => ({ ...repair, repairId: `r${index}`, repairNo: `FX${String(index).padStart(3, "0")}`, status: "COMPLETED" as const }));
  const list = vi.spyOn(repairApi, "listSummaries").mockImplementation(async (params) => {
    const filtered = rows.filter(row=>!params?.keyword||row.repairNo.includes(params.keyword));
    return { items:filtered.slice(((params?.page??1)-1)*10,(params?.page??1)*10),total:filtered.length,page:params?.page??1,pageSize:10 };
  });
  vi.spyOn(repairApi, "archive").mockImplementation(async()=>{rows.pop();return {} as never;});
  const wrapper = mount(RepairsPage, { global: { stubs: { AdminShell: shellStub } } });
  await flushPromises();
  expect(list).toHaveBeenCalledTimes(1);
  expect(list).toHaveBeenCalledWith(expect.objectContaining({page:1,pageSize:10}));
  await wrapper.get("button[aria-label='第 11 页']").trigger("click");
  await flushPromises();
  expect(wrapper.get(".repair-list-table tbody").text()).toContain("FX100");
  expect(wrapper.get(".order-sequence-cell").text()).toBe("101");
  await wrapper.get(".repair-archive-button").trigger("click");
  await wrapper.get("[data-repair-archive-confirm]").trigger("click");
  await flushPromises();
  expect(wrapper.get("button[aria-current=page]").text()).toBe("10");
  expect(wrapper.get(".order-page-total").text()).toBe("共 100 条");
  await wrapper.get("input[type=search]").setValue("FX000");
  await flushPromises();
  expect(wrapper.get("button[aria-current=page]").text()).toBe("1");
  expect(wrapper.findAll(".repair-list-table tbody tr")).toHaveLength(1);
  wrapper.unmount();
});

it("shows the first page without waiting for factory options and ignores stale list replies", async () => {
  let resolveOptions!: (value:{items:string[]})=>void;
  vi.mocked(repairApi.listFactoryOptions).mockReturnValue(new Promise(resolve=>{resolveOptions=resolve;}));
  let resolveOld!: (value:{items:Repair[];total:number;page:number;pageSize:number})=>void;
  const list=vi.spyOn(repairApi,"listSummaries")
    .mockReturnValueOnce(new Promise(resolve=>{resolveOld=resolve;}))
    .mockResolvedValue({items:[{...repair,repairNo:"new"}],total:1,page:1,pageSize:10});
  const wrapper=mount(RepairsPage,{global:{stubs:{AdminShell:shellStub}}});
  await wrapper.get("input[type=search]").setValue("new");
  await flushPromises();
  expect(list).toHaveBeenCalledTimes(2);
  expect(wrapper.get("tbody").text()).toContain("new");
  resolveOld({items:[repair],total:1,page:1,pageSize:10});
  resolveOptions({items:["其他工厂","宇婷"]});
  await flushPromises();
  expect(wrapper.get("tbody").text()).not.toContain(repair.repairNo);
  await wrapper.get(".order-multiselect-trigger").trigger("click");
  expect(wrapper.get(".order-multiselect-menu").text()).toContain("其他工厂");
  wrapper.unmount();
});

it("keeps list data when factory options fail and batches sorting with page reset", async()=>{
  vi.mocked(repairApi.listFactoryOptions).mockRejectedValue(new Error("options"));
  const list=vi.spyOn(repairApi,"listSummaries").mockResolvedValue({items:[repair],total:30,page:1,pageSize:10});
  const wrapper=mount(RepairsPage,{global:{stubs:{AdminShell:shellStub}}});
  await flushPromises();
  expect(wrapper.get("tbody").text()).toContain(repair.repairNo);
  expect(wrapper.get(".page-error").text()).toContain("工厂筛选选项加载失败");
  await wrapper.get("button[aria-label='第 2 页']").trigger("click");
  await flushPromises();
  list.mockClear();
  await wrapper.findAll(".data-grid-sort-button")[1]!.trigger("click");
  await flushPromises();
  expect(list).toHaveBeenCalledTimes(1);
  expect(list).toHaveBeenCalledWith(expect.objectContaining({page:1,sortBy:"factoryName",sortOrder:"asc"}));
  wrapper.unmount();
});

it("shares click/drop upload and creates only valid files, retrying no successes", async () => {
  vi.spyOn(repairApi, "upload").mockImplementation(async file => {
    if (file.name === "坏单.xlsx") throw new Error("第 2 行数量必须为正整数");
    return {...preview, previewId:file.name, originalFilename:file.name};
  });
  const confirm = vi.spyOn(repairApi, "confirm").mockResolvedValue(repair);
  const wrapper=mount(RepairCreatePage,{global:{stubs:{AdminShell:shellStub}}});
  await wrapper.get('.repair-upload-zone').trigger('drop', {dataTransfer:{files:[new File(['a'],'好单.xlsx'),new File(['b'],'坏单.xlsx')]}});
  await flushPromises();
  expect(wrapper.text()).toContain('坏单.xlsx');
  expect(wrapper.text()).toContain('第 2 行数量必须为正整数');
  expect(wrapper.find('table').exists()).toBe(false);
  expect(confirm).not.toHaveBeenCalled();
  await wrapper.get('[data-confirm-create]').trigger('click');
  await flushPromises();
  expect(confirm).toHaveBeenCalledTimes(1);
  expect(confirm).toHaveBeenCalledWith('好单.xlsx', expect.any(String));
  expect(wrapper.get('[data-confirm-create]').attributes('disabled')).toBeDefined();
  expect(wrapper.text()).toContain('创建成功');
  wrapper.unmount();
});

it("removes pending files from confirmation and keeps created records", async () => {
  vi.spyOn(repairApi, "upload").mockResolvedValueOnce({...preview,previewId:"removed"}).mockResolvedValueOnce({...preview,previewId:"kept"});
  const confirm=vi.spyOn(repairApi,"confirm").mockResolvedValue(repair);
  const wrapper=mount(RepairCreatePage,{global:{stubs:{AdminShell:shellStub}}});
  const input=wrapper.get<HTMLInputElement>('input[type="file"]');
  Object.defineProperty(input.element,"files",{value:[new File(['a'],'a.xlsx'),new File(['b'],'b.xlsx')]});
  await input.trigger('change');await flushPromises();
  await wrapper.get('button[aria-label="移除 a.xlsx"]').trigger('click');
  expect(wrapper.text()).not.toContain('a.xlsx');
  await wrapper.get('[data-confirm-create]').trigger('click');await flushPromises();
  expect(confirm).toHaveBeenCalledTimes(1);
  expect(confirm).toHaveBeenCalledWith('kept',expect.any(String));
  expect(wrapper.find('.repair-file-remove').exists()).toBe(false);
  wrapper.unmount();
});

it("blocks oversized files, accepts the size boundary, and disables removal during upload", async () => {
  let finish!:(value:RepairPreview)=>void;
  const upload=vi.spyOn(repairApi,'upload').mockImplementation(()=>new Promise(resolve=>{finish=resolve;}));
  const large=new File(['a'],'large.xlsx'),boundary=new File(['b'],'boundary.xlsx');
  Object.defineProperty(large,'size',{value:20*1024*1024+1});
  Object.defineProperty(boundary,'size',{value:20*1024*1024});
  const wrapper=mount(RepairCreatePage,{global:{stubs:{AdminShell:shellStub}}});
  const input=wrapper.get<HTMLInputElement>('input[type="file"]');
  Object.defineProperty(input.element,'files',{value:[large,boundary]});
  await input.trigger('change');
  expect(wrapper.text()).toContain('文件超过 20 MiB');
  expect(upload).toHaveBeenCalledTimes(1);
  expect(upload).toHaveBeenCalledWith(boundary);
  expect(wrapper.get<HTMLButtonElement>('.repair-file-remove').element.disabled).toBe(true);
  finish(preview);await flushPromises();
  await wrapper.get('button[aria-label="移除 large.xlsx"]').trigger('click');
  await wrapper.get('button[aria-label="移除 boundary.xlsx"]').trigger('click');
  expect(wrapper.find('[data-confirm-create]').exists()).toBe(false);
  wrapper.unmount();
});


it("explains an upload gateway 413 response", async () => {
  vi.spyOn(repairApi,'upload').mockRejectedValue(new ApiError(413,'request_failed','请求失败，请稍后重试'));
  const wrapper=mount(RepairCreatePage,{global:{stubs:{AdminShell:shellStub}}});
  const input=wrapper.get<HTMLInputElement>('input[type="file"]');
  Object.defineProperty(input.element,'files',{value:[new File(['a'],'failed.xlsx')]});
  await input.trigger('change');await flushPromises();
  expect(wrapper.text()).toContain('文件超过上传入口大小限制');
  expect(wrapper.get<HTMLButtonElement>('[data-confirm-create]').element.disabled).toBe(true);
  wrapper.unmount();
});
