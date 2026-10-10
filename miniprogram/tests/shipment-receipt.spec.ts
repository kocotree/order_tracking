/// <reference types="node" />
import { afterEach, expect, it, vi } from "vitest";
import { readFileSync } from "node:fs";
import { PREVIEW_SHIPMENT } from "../modules/dev-preview";
import type { Shipment } from "../api/shipments";

interface DetailPage {
  data: { lineGroups: { total: number }[]; boxGroups: { total: number }[] };
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
  expect(page.data).not.toHaveProperty("receiptAtText");
  expect(page.data.lineGroups.every(group => group.total === 0)).toBe(true);
  expect(page.data.boxGroups.every(box => box.total === 0)).toBe(true);
  expect(page.data.boxGroups).toHaveLength(PREVIEW_SHIPMENT.totalBoxes);
});

it.each([true, false])("factory withdrawal uses server eligibility (%s)", async canWithdraw => {
  vi.resetModules();
  type WithdrawalPage = DetailPage & { data: DetailPage["data"] & { withdrawStep: string }; openWithdraw(): void };
  let page!: WithdrawalPage;
  vi.stubGlobal("Page", (definition: WithdrawalPage) => { page = definition; page.setData = data => Object.assign(page.data, data); });
  await import("../pages/factory-shipment-detail/factory-shipment-detail");
  page.showShipment({ ...PREVIEW_SHIPMENT, files: [], canWithdraw,
    receipt: { status: "CONFIRMED", confirmedByName: null, confirmedAt: null },
  });
  page.openWithdraw();
  expect(page.data.withdrawStep).toBe(canWithdraw ? "form" : "");
});

it.each(["admin", "factory"])("%s template hides receipt confirmation information", role => {
  const source = readFileSync(new URL(`../pages/${role}-shipment-detail/${role}-shipment-detail.wxml`, import.meta.url), "utf8");
  expect(source).not.toContain("confirmedByName");
  expect(source).not.toContain("receiptAtText");
  expect(source).not.toContain("系统自动确认");
  expect(source).not.toContain("已收货");
  if (role === "factory") {
    expect(source).toContain("shipment.canWithdraw");
    expect(source).not.toContain("!shipment.receipt");
    expect(source).toContain("receiptDifferences");
  }
});
