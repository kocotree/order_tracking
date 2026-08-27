import { repairApi, type Repair } from "../../api/repairs";
import { isDevPreview, previewRepair } from "../../modules/dev-preview";
import { buildReturnEntries, prepareReturnSubmission, type ReturnEntry } from "../../modules/repair-return";

type ReturnGroup = { productName: string; pendingQuantity: number; entries: ReturnEntry[] };
type PreviewLine = ReturnEntry & { returnQuantity: number };

function groupsFor(repair: Repair): ReturnGroup[] {
  const groups = new Map<string, ReturnEntry[]>();
  buildReturnEntries(repair.specs).forEach((entry) => groups.set(entry.productName, [...(groups.get(entry.productName) ?? []), entry]));
  return Array.from(groups.entries()).map(([productName, entries]) => ({ productName, entries, pendingQuantity: entries.reduce((sum, entry) => sum + entry.pendingQuantity, 0) }));
}

function allEntries(groups: ReturnGroup[]): ReturnEntry[] { return groups.flatMap((group) => group.entries); }
function quantity(value: string): number { return /^\d+$/.test(value) ? Number(value) : 0; }
function totals(groups: ReturnGroup[]) { return allEntries(groups).filter((entry) => entry.selected).reduce((result, entry) => { result.repaired += quantity(entry.repaired); result.scrapped += quantity(entry.scrapped); result.total = result.repaired + result.scrapped; return result; }, { repaired: 0, scrapped: 0, total: 0 }); }
function previewLines(groups: ReturnGroup[]): PreviewLine[] { return allEntries(groups).filter((entry) => entry.selected).map((entry) => ({ ...entry, returnQuantity: quantity(entry.repaired) + quantity(entry.scrapped) })); }

function applyPreviewSubmission(repair: Repair, lines: Array<{ variantId: string; repairedQuantity: number; scrappedQuantity: number }>) {
  const batchLines = lines.map((line) => {
    const spec = repair.specs.find((item) => item.variantId === line.variantId)!;
    spec.repairedQuantity += line.repairedQuantity;
    spec.scrappedQuantity += line.scrappedQuantity;
    spec.returnedQuantity += line.repairedQuantity + line.scrappedQuantity;
    spec.pendingQuantity = Math.max(0, spec.warehouseReturnQuantity - spec.returnedQuantity);
    return { ...spec, repairedQuantity: line.repairedQuantity, scrappedQuantity: line.scrappedQuantity, returnedQuantity: line.repairedQuantity + line.scrappedQuantity };
  });
  repair.repairedQuantity = repair.specs.reduce((sum, spec) => sum + spec.repairedQuantity, 0);
  repair.scrappedQuantity = repair.specs.reduce((sum, spec) => sum + spec.scrappedQuantity, 0);
  repair.returnedQuantity = repair.repairedQuantity + repair.scrappedQuantity;
  repair.status = repair.returnedQuantity === repair.warehouseReturnQuantity ? "COMPLETED" : "INCOMPLETE";
  const returnDate = new Date().toISOString().slice(0, 10);
  repair.returnBatches.unshift({ batchId: `preview-batch-${Date.now()}`, submittedAt: new Date().toISOString(), returnDate, submittedBy: "preview-factory-user", lines: batchLines });
}

Page({
  data: { repair: null as Repair | null, repairId: "", loading: true, previewMode: false, step: "edit" as "edit" | "preview", progress: 0, pending: 0, groups: [] as ReturnGroup[], previewLines: [] as PreviewLine[], repairedTotal: 0, scrappedTotal: 0, returnTotal: 0, submitting: false, idempotencyKey: "" },
  onLoad(options: Record<string, string | undefined>) { const repairId = options.repairId ?? ""; const previewMode = isDevPreview(options); this.setData({ repairId, previewMode, idempotencyKey: `repair-return-${repairId}-${Date.now()}-${Math.random().toString(36).slice(2)}` }); if (repairId) void this.load(repairId, previewMode); },
  async load(repairId: string, previewMode: boolean) { try { const repair = previewMode ? previewRepair(repairId) : await repairApi.factoryGet(repairId); if (!repair || repair.status === "COMPLETED") { wx.navigateBack(); return; } const progress = repair.warehouseReturnQuantity ? Math.round(repair.returnedQuantity * 100 / repair.warehouseReturnQuantity) : 0; this.setData({ repair, progress, pending: Math.max(0, repair.warehouseReturnQuantity - repair.returnedQuantity), groups: groupsFor(repair) }); } catch { wx.showToast({ title: "返修任务加载失败", icon: "none" }); } finally { this.setData({ loading: false }); } },
  updateTotals() { const value = totals(this.data.groups); this.setData({ repairedTotal: value.repaired, scrappedTotal: value.scrapped, returnTotal: value.total }); },
  toggleEntry(event: WechatMiniprogram.TouchEvent) { const groupIndex = Number(event.currentTarget.dataset.group); const entryIndex = Number(event.currentTarget.dataset.entry); const selected = !this.data.groups[groupIndex]?.entries[entryIndex]?.selected; const changes: Record<string, boolean | string> = { [`groups[${groupIndex}].entries[${entryIndex}].selected`]: selected }; if (!selected) { changes[`groups[${groupIndex}].entries[${entryIndex}].repaired`] = ""; changes[`groups[${groupIndex}].entries[${entryIndex}].scrapped`] = ""; } this.setData(changes, () => this.updateTotals()); },
  changeQuantity(event: WechatMiniprogram.Input) { const groupIndex = Number(event.currentTarget.dataset.group); const entryIndex = Number(event.currentTarget.dataset.entry); const field = String(event.currentTarget.dataset.field); this.setData({ [`groups[${groupIndex}].entries[${entryIndex}].${field}`]: event.detail.value }, () => this.updateTotals()); },
  openPreview() { const prepared = prepareReturnSubmission(allEntries(this.data.groups)); if (!prepared.ok) { wx.showToast({ title: prepared.message, icon: "none" }); return; } this.setData({ step: "preview", previewLines: previewLines(this.data.groups) }); },
  edit() { this.setData({ step: "edit" }); },
  async submit() { if (!this.data.repair || this.data.submitting) return; const prepared = prepareReturnSubmission(allEntries(this.data.groups)); if (!prepared.ok) { wx.showToast({ title: prepared.message, icon: "none" }); return; } this.setData({ submitting: true }); try { if (this.data.previewMode) applyPreviewSubmission(this.data.repair, prepared.lines); else await repairApi.factorySubmitReturn(this.data.repairId, prepared.lines, this.data.idempotencyKey); wx.showToast({ title: "返修品发回记录已提交", icon: "success" }); setTimeout(() => wx.navigateBack(), 700); } catch (error) { const statusCode = (error as { statusCode?: number }).statusCode; wx.showToast({ title: statusCode === 409 ? "返修进度已变化，请重新核对" : "返修品发回失败", icon: "none" }); if (statusCode === 409) { this.setData({ step: "edit" }); await this.load(this.data.repairId, false); } } finally { this.setData({ submitting: false }); } },
  goBack() { if (this.data.step === "preview") { this.edit(); return; } wx.navigateBack(); },
});
