import { repairApi, type Repair, type RepairReturnBatch, type RepairReturnLine, type RepairSpec } from "../../api/repairs";
import { isDevPreview, previewRepair } from "../../modules/dev-preview";

type RepairSpecView = RepairSpec & { expanded?: boolean };
type RepairProductGroup = { productName: string; specCount: number; pendingQuantity: number; expanded: boolean; lines: RepairSpecView[] };
type ReturnLineView = RepairReturnLine & { returnedQuantity: number };
type ReturnBatchView = Omit<RepairReturnBatch, "lines"> & { expanded: boolean; returnedQuantity: number; lines: ReturnLineView[] };

function productGroups(repair: Repair): RepairProductGroup[] {
  const groups = new Map<string, RepairSpecView[]>();
  repair.specs.forEach((spec) => groups.set(spec.productName, [...(groups.get(spec.productName) ?? []), spec]));
  return Array.from(groups.entries()).map(([productName, lines]) => ({
    productName, specCount: lines.length,
    pendingQuantity: lines.reduce((total, line) => total + line.pendingQuantity, 0),
    expanded: false, lines,
  }));
}

function returnBatchViews(repair: Repair): ReturnBatchView[] {
  return repair.returnBatches.map((batch) => {
    const lines = batch.lines.map((line) => ({ ...line, returnedQuantity: line.repairedQuantity + line.scrappedQuantity }));
    return { ...batch, lines, expanded: false, returnedQuantity: lines.reduce((total, line) => total + line.returnedQuantity, 0) };
  });
}

Page({
  data: { repairId: "", repair: null as Repair | null, loading: true, progress: 0, pending: 0, returnDateText: "", previewMode: false, productGroups: [] as RepairProductGroup[], returnBatches: [] as ReturnBatchView[] },
  onLoad(options: Record<string, string | undefined>) { const previewMode = isDevPreview(options); const repairId = options.repairId ?? ""; this.setData({ previewMode, repairId }); if (repairId) void this.load(repairId, previewMode); },
  onShow() { if (this.data.repairId && !this.data.loading) void this.load(this.data.repairId, this.data.previewMode); },
  async load(repairId: string, previewMode = false) {
    this.setData({ loading: true });
    try {
      const repair = previewMode ? previewRepair(repairId) : await repairApi.factoryGet(repairId);
      if (!repair) throw new Error("返修演示数据不存在");
      const progress = repair.warehouseReturnQuantity ? Math.round(repair.returnedQuantity / repair.warehouseReturnQuantity * 100) : 0;
      const [, month = "", day = ""] = repair.returnDate.split("-");
      this.setData({ repair, progress, pending: Math.max(0, repair.warehouseReturnQuantity - repair.returnedQuantity), returnDateText: `${month}月${day}日`, productGroups: productGroups(repair), returnBatches: returnBatchViews(repair) });
    } catch { wx.showToast({ title: "返修任务加载失败", icon: "none" }); }
    finally { this.setData({ loading: false }); }
  },
  async download() { if (!this.data.repair) return; if (this.data.previewMode) { wx.showToast({ title: "演示模式不下载附件", icon: "none" }); return; } try { const path = await repairApi.download(this.data.repair.originalFileId); wx.openDocument({ filePath: path, showMenu: true }); } catch { wx.showToast({ title: "质检附件下载失败", icon: "none" }); } },
  toggleProduct(event: WechatMiniprogram.TouchEvent) { const index = Number(event.currentTarget.dataset.index); this.setData({ [`productGroups[${index}].expanded`]: !this.data.productGroups[index]?.expanded }); },
  toggleBatch(event: WechatMiniprogram.TouchEvent) { const index = Number(event.currentTarget.dataset.index); this.setData({ [`returnBatches[${index}].expanded`]: !this.data.returnBatches[index]?.expanded }); },
  openReturn() { if (!this.data.repair) return; const preview = this.data.previewMode ? "&preview=1" : ""; wx.navigateTo({ url: `/pages/factory-repair-return/factory-repair-return?repairId=${encodeURIComponent(this.data.repair.repairId)}${preview}` }); },
  goBack() { wx.navigateBack(); },
});
