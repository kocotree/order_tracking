export interface ReturnSpec {
  variantId: string;
  productName: string;
  propertiesValue: string;
  warehouseReturnQuantity: number;
  repairedQuantity: number;
  scrappedQuantity: number;
  returnedQuantity: number;
  pendingQuantity: number;
}

export interface ReturnEntry extends ReturnSpec {
  selected: boolean;
  repaired: string;
  scrapped: string;
}

export type PreparedReturn =
  | { ok: true; lines: Array<{ variantId: string; repairedQuantity: number; scrappedQuantity: number }> }
  | { ok: false; message: string };

export function buildReturnEntries(specs: ReturnSpec[]): ReturnEntry[] {
  return specs
    .filter((spec) => spec.pendingQuantity > 0)
    .map((spec) => ({ ...spec, selected: false, repaired: "", scrapped: "" }));
}

function isNonnegativeInteger(value: string): boolean {
  return value === "" || /^\d+$/.test(value);
}

function quantity(value: string): number {
  return /^\d+$/.test(value) ? Number(value) : 0;
}

export function prepareReturnSubmission(entries: ReturnEntry[]): PreparedReturn {
  const selected = entries.filter((entry) => entry.selected);
  if (!selected.length) return { ok: false, message: "请至少选择一个本次发回的产品规格" };

  const lines: Array<{ variantId: string; repairedQuantity: number; scrappedQuantity: number }> = [];
  for (const entry of selected) {
    if (!isNonnegativeInteger(entry.repaired) || !isNonnegativeInteger(entry.scrapped)) {
      return { ok: false, message: "返修数量和报废数量只能填写非负整数" };
    }
    const repairedQuantity = quantity(entry.repaired);
    const scrappedQuantity = quantity(entry.scrapped);
    if (repairedQuantity + scrappedQuantity === 0) {
      return { ok: false, message: `${entry.propertiesValue}的返修数量和报废数量不能同时为0` };
    }
    if (repairedQuantity + scrappedQuantity > entry.pendingQuantity) {
      return { ok: false, message: `${entry.propertiesValue}本次返回数量不能超过待返回数量` };
    }
    lines.push({ variantId: entry.variantId, repairedQuantity, scrappedQuantity });
  }
  return { ok: true, lines };
}
