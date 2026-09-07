import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { ReturnEntry } from "../modules/repair-return";

const api = vi.hoisted(() => ({ factoryGet: vi.fn(), factorySubmitReturn: vi.fn() }));
vi.mock("../api/repairs", () => ({ repairApi: api }));

type Event = { currentTarget: { dataset: { group: number; entry?: number; field?: string } }; detail: { value: string } };
type TestPage = {
  data: { groups: { expanded: boolean; entries: ReturnEntry[] }[]; step: string; repairedTotal: number; returnTotal: number; previewLines: ReturnEntry[] };
  setData(values: Record<string, unknown>, callback?: () => void): void;
  load(id: string, preview: boolean): Promise<void>;
  toggleGroup(event: Event): void;
  toggleEntry(event: Event): void;
  changeQuantity(event: Event): void;
  openPreview(): void;
  edit(): void;
};
let page: TestPage;
const event = (group: number, entry = 0, value = "", field = "repaired"): Event => ({ currentTarget: { dataset: { group, entry, field } }, detail: { value } });

beforeEach(async () => {
  vi.resetModules();
  api.factoryGet.mockResolvedValue({
    status: "INCOMPLETE", warehouseReturnQuantity: 30, returnedQuantity: 0,
    specs: ["甲", "甲", "乙"].map((productName, index) => ({ variantId: `sku-${index}`, productName, propertiesValue: `规格${index}`, warehouseReturnQuantity: 10, returnedQuantity: 0, pendingQuantity: 10 })),
  });
  vi.stubGlobal("wx", { showToast: vi.fn() });
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
afterEach(() => vi.unstubAllGlobals());

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
