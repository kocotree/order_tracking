import { RepairDraftSession } from "../../modules/repair-return-draft";
import { repairApi, type Repair, type RepairDraftEntry } from "../../api/repairs";
import { isDevPreview, previewRepair } from "../../modules/dev-preview";
import { prepareReturnSubmission, type ReturnEntry } from "../../modules/repair-return";

type ReturnGroup = { expanded: boolean; productName: string; pendingQuantity: number; entries: ReturnEntry[] };
type PreviewGroup = { productName: string; expanded: boolean; lines: PreviewLine[] };
type PreviewLine = ReturnEntry & { returnQuantity: number };

function groupsFor(repair: Repair, draft: RepairDraftEntry[] = []): ReturnGroup[] {
  const saved = new Map(draft.map(entry => [entry.variantId, entry]));
  const groups = new Map<string, ReturnEntry[]>();
  repair.specs.filter(spec => spec.pendingQuantity > 0 || saved.has(spec.variantId)).map(spec => ({ ...spec, selected: false, repaired: "", scrapped: "", ...saved.get(spec.variantId) })).forEach((entry) => groups.set(entry.productName, [...(groups.get(entry.productName) ?? []), entry]));
  return Array.from(groups.entries()).map(([productName, entries]) => ({ expanded: false, productName, entries, pendingQuantity: entries.reduce((sum, entry) => sum + entry.pendingQuantity, 0) }));
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

function draftEntries(groups: ReturnGroup[]): RepairDraftEntry[] {
  return allEntries(groups).filter(entry => entry.selected || entry.repaired || entry.scrapped).map(({variantId, selected, repaired, scrapped}) => ({variantId, selected, repaired, scrapped}));
}

Page({
  draftSession: null as RepairDraftSession | null,
  saveTimer: null as ReturnType<typeof setTimeout> | null,
  pageClosed: false,
  submitted: false,
  data: { ready: false, saveMessage: "", repair: null as Repair | null, repairId: "", loading: true, previewMode: false, step: "edit" as "edit" | "preview", progress: 0, pending: 0, groups: [] as ReturnGroup[], previewLines: [] as PreviewLine[], previewGroups: [] as PreviewGroup[], repairedTotal: 0, scrappedTotal: 0, returnTotal: 0, submitting: false, idempotencyKey: "" },
  onLoad(options: Record<string, string | undefined>) { const repairId = options.repairId ?? ""; const previewMode = isDevPreview(options); this.setData({ repairId, previewMode, idempotencyKey: `repair-return-${repairId}-${Date.now()}-${Math.random().toString(36).slice(2)}` }); if (repairId) void this.load(repairId, previewMode); },
  async load(repairId: string, previewMode: boolean) {
    this.setData({ ready: false });
    try {
      const repair = previewMode ? previewRepair(repairId) : await repairApi.factoryGet(repairId);
      if (!repair || repair.status === "COMPLETED") { wx.navigateBack(); return; }
      const draft = previewMode ? { version: 0, entries: [], submissionKey: "" } : await repairApi.getReturnDraft(repairId);
      this.draftSession = previewMode ? null : new RepairDraftSession(repairApi, repairId, draft);
      this.setData({ repair, progress: repair.warehouseReturnQuantity ? Math.round(repair.returnedQuantity * 100 / repair.warehouseReturnQuantity) : 0, pending: Math.max(0, repair.warehouseReturnQuantity - repair.returnedQuantity), groups: groupsFor(repair, draft.entries), ready: true, saveMessage: draft.entries.length ? "已恢复上次草稿，请核对最新待返回数量" : "" });
      this.updateTotals();
    } catch { this.setData({ saveMessage: "草稿或返修任务加载失败，请退出后重试" }); wx.showToast({ title: "草稿加载失败", icon: "none" }); }
    finally { this.setData({ loading: false }); }
  },
  scheduleSave() {
    if (this.data.previewMode || !this.data.ready || this.data.submitting || this.submitted) return;
    this.setData({ saveMessage: "有修改尚未保存" });
    if (this.saveTimer) clearTimeout(this.saveTimer);
    this.saveTimer = setTimeout(() => { this.saveTimer = null; void this.saveDraftNow(); }, 500);
  },
  async saveDraftNow(): Promise<boolean> {
    if (this.saveTimer) { clearTimeout(this.saveTimer); this.saveTimer = null; }
    if (this.data.previewMode || this.submitted) return true;
    if (!this.data.ready || !this.draftSession) return false;
    if (!this.pageClosed) this.setData({ saveMessage: "正在保存草稿…" });
    try {
      const draft = await this.draftSession.save(draftEntries(this.data.groups));
      if (JSON.stringify(draft.entries) !== JSON.stringify(draftEntries(this.data.groups))) return this.saveDraftNow();
      if (!this.pageClosed) this.setData({ saveMessage: "草稿已保存" });
      return true;
    } catch (error) {
      if (!this.pageClosed) this.setData({ saveMessage: (error as {statusCode?: number}).statusCode === 409 ? "草稿已在其他页面更新，请重新进入核对" : "草稿未保存，请检查网络后重试" });
      return false;
    }
  },
  onHide() { if (this.data.ready && !this.data.submitting && !this.submitted) void this.saveDraftNow(); },
  onUnload() { this.pageClosed = true; if (this.saveTimer) clearTimeout(this.saveTimer); if (this.data.ready && !this.data.submitting && !this.submitted) void this.saveDraftNow(); },

  updateTotals() { const value = totals(this.data.groups); this.setData({ repairedTotal: value.repaired, scrappedTotal: value.scrapped, returnTotal: value.total }); },
  toggleGroup(event: WechatMiniprogram.TouchEvent) {
    const index = Number(event.currentTarget.dataset.group);
    const group = this.data.groups[index];
    if (group) this.setData({ [`groups[${index}].expanded`]: !group.expanded });
  },
  togglePreviewGroup(event: WechatMiniprogram.TouchEvent) {
    const index = Number(event.currentTarget.dataset.group);
    const group = this.data.previewGroups[index];
    if (group) this.setData({ [`previewGroups[${index}].expanded`]: !group.expanded });
  },
  openPreview() { if (!this.data.ready || this.data.submitting) return; const prepared = prepareReturnSubmission(allEntries(this.data.groups)); if (!prepared.ok) { wx.showToast({ title: prepared.message, icon: "none" }); return; } const lines = previewLines(this.data.groups); const groups = new Map<string, PreviewLine[]>(); lines.forEach((line) => groups.set(line.productName, [...(groups.get(line.productName) ?? []), line])); this.setData({ step: "preview", previewLines: lines, previewGroups: Array.from(groups, ([productName, groupLines]) => ({ productName, expanded: false, lines: groupLines })) }); },
  toggleEntry(event: WechatMiniprogram.TouchEvent) { if (!this.data.ready || this.data.submitting) return; const groupIndex = Number(event.currentTarget.dataset.group); const entryIndex = Number(event.currentTarget.dataset.entry); const selected = !this.data.groups[groupIndex]?.entries[entryIndex]?.selected; const changes: Record<string, boolean | string> = { [`groups[${groupIndex}].entries[${entryIndex}].selected`]: selected }; if (!selected) { changes[`groups[${groupIndex}].entries[${entryIndex}].repaired`] = ""; changes[`groups[${groupIndex}].entries[${entryIndex}].scrapped`] = ""; } this.setData(changes, () => { this.updateTotals(); this.scheduleSave(); }); },
  changeQuantity(event: WechatMiniprogram.Input) { if (!this.data.ready || this.data.submitting) return; const groupIndex = Number(event.currentTarget.dataset.group); const entryIndex = Number(event.currentTarget.dataset.entry); const field = String(event.currentTarget.dataset.field); this.setData({ [`groups[${groupIndex}].entries[${entryIndex}].${field}`]: event.detail.value }, () => { this.updateTotals(); this.scheduleSave(); }); },
  edit() { this.setData({ step: "edit" }); },
  async submit() { if (!this.data.repair || !this.data.ready || this.data.submitting) return; const prepared = prepareReturnSubmission(allEntries(this.data.groups)); if (!prepared.ok) { wx.showToast({ title: prepared.message, icon: "none" }); return; } this.setData({ submitting: true }); try { if (!await this.saveDraftNow()) return; if (this.data.previewMode) applyPreviewSubmission(this.data.repair, prepared.lines); else await repairApi.factorySubmitReturn(this.data.repairId, prepared.lines, this.draftSession!.current.submissionKey, this.draftSession!.current.version); this.submitted = true; wx.showToast({ title: "返修品发回记录已提交", icon: "success" }); setTimeout(() => wx.navigateBack(), 700); } catch (error) { const statusCode = (error as { statusCode?: number }).statusCode; wx.showToast({ title: statusCode === 409 ? "返修进度已变化，请重新核对" : "返修品发回失败", icon: "none" }); if (statusCode === 409) { this.setData({ step: "edit" }); this.setData({ saveMessage: "返修进度或草稿已变化，请退出后重新进入核对" }); } } finally { this.setData({ submitting: false }); } },
  async goBack() { if (this.data.submitting) return; if (this.data.step === "preview") { this.edit(); return; } if (!this.data.ready || await this.saveDraftNow()) wx.navigateBack(); },
});
