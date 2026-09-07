import { afterEach, expect, it, vi } from "vitest";
import { PREVIEW_SHIPMENT } from "../modules/dev-preview";
import type { Shipment } from "../api/shipments";

interface DetailPage {
  data: { receiptAtText: string; lineGroups: { total: number }[]; boxGroups: { total: number }[] };
  setData(data: Partial<DetailPage["data"]>): void;
  showShipment(shipment: Shipment): void;
}

afterEach(() => vi.unstubAllGlobals());
it.each(["admin", "factory"])("%s detail displays confirmed quantities including zero boxes", async role => {
  vi.resetModules();
  let page!: DetailPage;
  vi.stubGlobal("Page", (definition: DetailPage) => { page = definition; page.setData = data => Object.assign(page.data, data); });
  if (role === "admin") await import("../pages/admin-shipment-detail/admin-shipment-detail");
  else await import("../pages/factory-shipment-detail/factory-shipment-detail");
  page.showShipment({ ...PREVIEW_SHIPMENT, files: [], totalQuantity: 0,
    lines: PREVIEW_SHIPMENT.lines.map(line => ({ ...line, quantity: 0 })),
    boxes: PREVIEW_SHIPMENT.boxes.map(box => ({ ...box, items: box.items.map(item => ({ ...item, quantity: 0 })) })),
    receipt: { status: "CONFIRMED", confirmedByName: "管理员", confirmedAt: "2026-09-07T02:00:00" },
  });
  expect(page.data.receiptAtText).toBe("2026-09-07 10:00");
  expect(page.data.lineGroups.every(group => group.total === 0)).toBe(true);
  expect(page.data.boxGroups.every(box => box.total === 0)).toBe(true);
  expect(page.data.boxGroups).toHaveLength(PREVIEW_SHIPMENT.totalBoxes);
});
