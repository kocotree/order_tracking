import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { ReturnEntry } from "../modules/repair-return";

const api = vi.hoisted(() => ({ factoryGet: vi.fn(), getReturnDraft: vi.fn(), saveReturnDraft: vi.fn(), factorySubmitReturn: vi.fn() }));
vi.mock("../api/repairs", () => ({ repairApi: api }));

type Event = { currentTarget: { dataset: { group: number; entry?: number; field?: string } }; detail: { value: string } };
type TestPage = {
  data: { groups: { expanded: boolean; entries: ReturnEntry[] }[]; step: string; repairedTotal: number; returnTotal: number; previewLines: ReturnEntry[]; ready: boolean; saveMessage: string };
  setData(values: Record<string, unknown>, callback?: () => void): void;
  load(id: string, preview: boolean): Promise<void>;
  toggleGroup(event: Event): void;
  toggleEntry(event: Event): void;
  changeQuantity(event: Event): void;
  openPreview(): void;
  edit(): void;
  saveDraftNow(): Promise<boolean>;
  goBack(): Promise<void>;
  onHide(): void;
  submit(): Promise<void>;
};
let page: TestPage;
const event = (group: number, entry = 0, value = "", field = "repaired"): Event => ({ currentTarget: { dataset: { group, entry, field } }, detail: { value } });

beforeEach(async () => {
  vi.resetModules();
  vi.useFakeTimers();
  api.saveReturnDraft.mockReset();
  api.factorySubmitReturn.mockReset();
  api.getReturnDraft.mockResolvedValue({ version: 0, entries: [], submissionKey: "" });
  api.factoryGet.mockResolvedValue({
    status: "INCOMPLETE", warehouseReturnQuantity: 30, returnedQuantity: 0,
    specs: ["甲", "甲", "乙"].map((productName, index) => ({ variantId: `sku-${index}`, productName, propertiesValue: `规格${index}`, warehouseReturnQuantity: 10, returnedQuantity: 0, pendingQuantity: 10 })),
  });
  vi.stubGlobal("wx", { showToast: vi.fn(), navigateBack: vi.fn() });
  vi.stubGlobal("Page", (definition: TestPage) => {
    page = { ...definition, data: structuredClone(definition.data), setData(values, callback) {
      for (const [path, value] of Object.entries(values)) {
        const keys = path.replace(/\[(\d+)\]/g, ".$1").split(".");
        let target = this.data as unknown as Record<string, unknown>;
        for (const key of keys.slice(0, -1)) target = target[key] as Record<string, unknown>;
        target[keys[keys.length - 1]] = value;
      }
      callback?.();
    } };
  });
  await import("../pages/factory-repair-return/factory-repair-return");
  await page.load("repair-1", false);
});
afterEach(() => { vi.clearAllTimers(); vi.useRealTimers(); vi.unstubAllGlobals(); });

it("starts each product collapsed and expands all of that product's SKUs independently", () => {
  expect(page.data.groups.map(group => group.expanded)).toEqual([false, false]);
  page.toggleGroup(event(0));
  expect(page.data.groups.map(group => group.expanded)).toEqual([true, false]);
  expect(page.data.groups[0].entries).toHaveLength(2);
  page.toggleGroup(event(0));
  expect(page.data.groups.map(group => group.expanded)).toEqual([false, false]);
});

it("preserves selected quantities and includes collapsed products when previewing", () => {
  page.toggleGroup(event(0));
  page.toggleEntry(event(0));
  page.changeQuantity(event(0, 0, "6"));
  page.changeQuantity(event(0, 0, "2", "scrapped"));
  page.toggleGroup(event(0));
  expect(page.data.returnTotal).toBe(8);
  page.openPreview();
  expect(page.data.step).toBe("preview");
  expect(page.data.previewLines).toEqual([expect.objectContaining({ variantId: "sku-0", repaired: "6", scrapped: "2" })]);
  page.edit();
  page.toggleGroup(event(0));
  expect(page.data.groups[0].entries[0]).toMatchObject({ selected: true, repaired: "6", scrapped: "2" });
});

it("still validates invalid quantities inside a collapsed product", () => {
  page.toggleEntry(event(0));
  page.changeQuantity(event(0, 0, "11"));
  page.openPreview();
  expect(page.data.step).toBe("edit");
  expect(wx.showToast).toHaveBeenCalledWith(expect.objectContaining({ title: expect.stringContaining("不能超过待返回数量") }));
});

it("restores partial input against latest quantities and saves before leaving", async () => {
  const entries = [{variantId: "sku-0", selected: true, repaired: "", scrapped: "2"}];
  api.getReturnDraft.mockResolvedValue({version: 3, entries, submissionKey: "key"});
  await page.load("repair-1", false);
  expect(page.data.groups[0].entries[0]).toMatchObject({selected: true, repaired: "", scrapped: "2", pendingQuantity: 10});
  page.changeQuantity(event(0, 0, "4"));
  api.saveReturnDraft.mockResolvedValue({version: 4, entries: [{...entries[0], repaired: "4"}], submissionKey: "key"});
  await page.goBack();
  expect(api.saveReturnDraft).toHaveBeenCalledWith("repair-1", 3, [{...entries[0], repaired: "4"}]);
  expect(wx.navigateBack).toHaveBeenCalledTimes(1);
});

it("does not permit overwriting a draft that could not be loaded", async () => {
  api.getReturnDraft.mockRejectedValue(new Error("offline"));
  await page.load("repair-1", false);
  expect(page.data.ready).toBe(false);
  expect(await page.saveDraftNow()).toBe(false);
  expect(api.saveReturnDraft).not.toHaveBeenCalled();
});

it("does not claim a failed save succeeded or leave on active back", async () => {
  page.toggleEntry(event(0));
  api.saveReturnDraft.mockRejectedValue({statusCode: 500});
  await page.goBack();
  expect(wx.navigateBack).not.toHaveBeenCalled();
  expect(page.data.saveMessage).toContain("未保存");
});

it("keeps restored selections with zero remaining quantity visible for correction", async () => {
  const repair = await api.factoryGet();
  repair.specs[0].pendingQuantity = 0;
  api.getReturnDraft.mockResolvedValue({version: 2, entries: [{variantId: "sku-0", selected: true, repaired: "4", scrapped: ""}], submissionKey: "key"});
  await page.load("repair-1", false);
  expect(page.data.groups[0].entries[0].pendingQuantity).toBe(0);
  page.openPreview();
  expect(page.data.step).toBe("edit");
  expect(wx.showToast).toHaveBeenCalledWith(expect.objectContaining({title: expect.stringContaining("不能超过待返回数量")}));
});

it("flushes before submitting and does not recreate a draft when hiding after success", async () => {
  page.toggleEntry(event(0));
  page.changeQuantity(event(0, 0, "2"));
  const entries = [{variantId: "sku-0", selected: true, repaired: "2", scrapped: ""}];
  api.saveReturnDraft.mockResolvedValue({version: 1, entries, submissionKey: "key"});
  api.factorySubmitReturn.mockResolvedValue({});
  await page.submit();
  expect(api.factorySubmitReturn).toHaveBeenCalledWith("", [{variantId: "sku-0", repairedQuantity: 2, scrappedQuantity: 0}], "key", 1);
  page.onHide();
  expect(api.saveReturnDraft).toHaveBeenCalledTimes(1);
});

it("waits for edits made during a save before navigating back", async () => {
  let finish!: (value: unknown) => void;
  page.toggleEntry(event(0));
  page.changeQuantity(event(0, 0, "2"));
  api.saveReturnDraft.mockImplementationOnce(() => new Promise(resolve => { finish = resolve; })).mockResolvedValueOnce({version: 2, entries: [{variantId: "sku-0", selected: true, repaired: "3", scrapped: ""}], submissionKey: "key"});
  const leaving = page.goBack();
  page.changeQuantity(event(0, 0, "3"));
  expect(wx.navigateBack).not.toHaveBeenCalled();
  finish({version: 1, entries: [{variantId: "sku-0", selected: true, repaired: "2", scrapped: ""}], submissionKey: "key"});
  await leaving;
  expect(api.saveReturnDraft).toHaveBeenCalledTimes(2);
  expect(wx.navigateBack).toHaveBeenCalledTimes(1);
});
