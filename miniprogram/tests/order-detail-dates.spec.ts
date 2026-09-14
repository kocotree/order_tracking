import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { Order } from "../api/orders";
import { previewOrder } from "../modules/dev-preview";

type DetailPage = {
  data: {
    contractShipDateText: string;
    showDetailContractDates: boolean;
    order: Omit<Order, "lines"> & { lines: (Order["lines"][number] & { contractShipDateText: string })[] };
    factoryProgress: {
      contractShipDateText: string;
      showDetailContractDates: boolean;
      products: { contractShipDateText: string }[];
    }[];
  };
  show(order: Order): void;
  setData(values: Partial<DetailPage["data"]>): void;
};
let page: DetailPage;

beforeEach(() => {
  vi.resetModules();
  vi.stubGlobal("Page", (definition: DetailPage) => {
    page = { ...definition, data: { ...definition.data }, setData(values) { Object.assign(this.data, values); } };
  });
});
afterEach(() => { vi.unstubAllGlobals(); });

it.each([false, true])("factory detail date visibility for multiple dates = %s", async (multiple) => {
  await import("../pages/factory-task-detail/factory-task-detail");
  const order = previewOrder(true);
  const line = order.lines[0];
  order.lines = [
    { ...line, assignments: [{ ...line.assignments[0], contractShipDate: "2026-08-30" }] },
    { ...line, orderLineId: line.orderLineId + 1, assignments: [{ ...line.assignments[0], contractShipDate: multiple ? "2026-08-31" : "2026-08-30" }] },
  ];
  order.contractShipDates = multiple ? ["2026-08-31", "2026-08-30", "2026-08-31"] : ["2026-08-30", "2026-08-30"];
  page.show(order);
  expect(page.data.showDetailContractDates).toBe(multiple);
  expect(page.data.contractShipDateText).toBe(multiple ? "2026-08-30、2026-08-31" : "2026-08-30");
  expect(page.data.order.lines.map(item => item.contractShipDateText)).toEqual(["2026-08-30", multiple ? "2026-08-31" : "2026-08-30"]);
});

it.each([false, true])("admin groups dates per factory, multiple dates = %s", async (multiple) => {
  await import("../pages/admin-order-detail/admin-order-detail");
  const order = previewOrder();
  const line = order.lines[0];
  const assignment = line.assignments[0];
  order.factoryProgress.push({ ...order.factoryProgress[0], factoryId: "other-factory", factoryName: "其他工厂" });
  order.lines = [
    { ...line, assignments: [{ ...assignment, contractShipDate: "2026-08-31" }, { ...assignment, factoryId: "other-factory", contractShipDate: "2026-09-10" }] },
    { ...line, orderLineId: line.orderLineId + 1, assignments: [{ ...assignment, contractShipDate: multiple ? "2026-08-30" : "2026-08-31" }] },
  ];
  page.show(order);
  const [factory, other] = page.data.factoryProgress;
  expect(factory.contractShipDateText).toBe(multiple ? "2026-08-30、2026-08-31" : "2026-08-31");
  expect(factory.showDetailContractDates).toBe(multiple);
  expect(factory.products.map(product => product.contractShipDateText)).toEqual(["2026-08-31", multiple ? "2026-08-30" : "2026-08-31"]);
  expect(other.contractShipDateText).toBe("2026-09-10");
  expect(other.showDetailContractDates).toBe(false);
});
