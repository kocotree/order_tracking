import { beforeEach, expect, it, vi } from "vitest";
import { previewOrder } from "../modules/dev-preview";

const mocks = vi.hoisted(() => ({ get: vi.fn(), incomingDifferences: vi.fn() }));
vi.mock("../api/orders", () => ({ orderApi: mocks }));

type Group = { productName: string; rows: { sequence: number; spec: string; quantityText: string; shortage: boolean }[] };
type DetailPage = {
  data: { incomingGroups: Group[]; incomingExpanded: boolean; loading: boolean; order: unknown };
  setData(values: Record<string, unknown>): void;
  load(orderId: string): Promise<void>;
  toggleIncoming(): void;
};
let page: DetailPage;

beforeEach(async () => {
  vi.resetModules();
  mocks.get.mockReset().mockResolvedValue(previewOrder(true));
  mocks.incomingDifferences.mockReset().mockResolvedValue({ items: [] });
  vi.stubGlobal("Page", (definition: DetailPage) => {
    page = { ...definition, data: { ...definition.data }, setData(values) { Object.assign(this.data, values); } };
  });
  await import("../pages/factory-task-detail/factory-task-detail");
});

it("keeps the empty section hidden and groups records in registration order", async () => {
  await page.load("order-1");
  expect(page.data.incomingGroups).toEqual([]);
  mocks.incomingDifferences.mockResolvedValue({ items: [
    { sequence: 3, productName: "衣服", spec: "蓝 / 110", quantity: -1 },
    { sequence: 1, productName: "衣服", spec: "蓝 / 110", quantity: -2 },
    { sequence: 2, productName: "帽子", spec: "红", quantity: 1 },
  ] });
  await page.load("order-1");
  expect(mocks.incomingDifferences).toHaveBeenCalledWith("order-1");
  expect(page.data.incomingGroups).toEqual([
    { productName: "衣服", rows: [{ sequence: 1, spec: "蓝 / 110", quantityText: "少2件", shortage: true }, { sequence: 3, spec: "蓝 / 110", quantityText: "少1件", shortage: true }] },
    { productName: "帽子", rows: [{ sequence: 2, spec: "红", quantityText: "多1件", shortage: false }] },
  ]);
  expect(page.data.incomingExpanded).toBe(false);
  page.toggleIncoming();
  expect(page.data.incomingExpanded).toBe(true);
});
