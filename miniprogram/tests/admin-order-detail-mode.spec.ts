import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { Order } from "../api/orders";
import { previewOrder } from "../modules/dev-preview";

type FactoryView = {
  factoryId: string;
  factoryName: string;
  progressPercent: number;
  orderText: string;
  shippedText: string;
  pendingText: string;
  products: { key: string; index: number; productName: string; propertiesValue: string; assignedText: string }[];
};
type DetailPage = {
  data: { factoryProgress: FactoryView[]; productSummary: string };
  show(order: Order): void;
  setData(values: Partial<DetailPage["data"]>): void;
};
let page: DetailPage;

function detail(values: Partial<Order["details"][number]>): Order["details"][number] {
  return {
    category: null, contractShipDate: "2026-08-31", detailId: "d1", dispatchState: "ASSIGNED",
    factoryName: "昱斌", itemNumber: null, matchedFactoryId: null, matchedVariantId: null,
    orderQuantity: 100, origin: "feishu", pendingQuantity: 40, productName: "晴雨两用风衣",
    progressPercent: 60, propertiesValue: "黑色/M", rawFields: {}, shippedQuantity: 60,
    sourceSkuId: null, sourceTracker: null, sourceTrackers: [], version: 1,
    ...values,
  };
}

beforeEach(() => {
  vi.resetModules();
  vi.stubGlobal("Page", (definition: DetailPage) => {
    page = { ...definition, data: { ...definition.data }, setData(values) { Object.assign(this.data, values); } };
  });
});
afterEach(() => { vi.unstubAllGlobals(); });

it("groups details by factory name regardless of dispatch state", async () => {
  await import("../pages/admin-order-detail/admin-order-detail");
  const order = previewOrder();
  order.detailMode = true;
  order.lines = [];
  order.factoryProgress = [];
  order.details = [
    detail({ detailId: "d1" }),
    detail({ detailId: "d2", dispatchState: "UNASSIGNED", productName: "儿童遮阳帽", orderQuantity: 200, shippedQuantity: 50, pendingQuantity: 150 }),
    detail({ detailId: "d3", factoryName: "宇倩", orderQuantity: null, pendingQuantity: null }),
    detail({ detailId: "d4", factoryName: null, productName: null, propertiesValue: null }),
  ];
  page.show(order);

  const [first, second, third] = page.data.factoryProgress;
  expect(page.data.factoryProgress.map((item) => item.factoryName)).toEqual(["昱斌", "宇倩", "—"]);
  expect(first.products.map((item) => item.key)).toEqual(["d1", "d2"]);
  expect(first.products.map((item) => item.index)).toEqual([1, 2]);
  expect([first.orderText, first.shippedText, first.pendingText]).toEqual(["300", "110", "190"]);
  expect(first.progressPercent).toBe(37);
  expect([second.orderText, second.pendingText]).toEqual(["—", "—"]);
  expect(second.progressPercent).toBe(0);
  expect(third.factoryId).toBe("—");
  expect(third.products[0]).toMatchObject({ productName: "—", propertiesValue: "—" });
  expect(page.data.productSummary).toBe("晴雨两用风衣、儿童遮阳帽");
});
