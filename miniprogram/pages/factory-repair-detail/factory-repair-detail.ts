import { repairApi, type Repair } from "../../api/repairs";
import { isDevPreview, previewRepair } from "../../modules/dev-preview";

type RepairLine = Repair["lines"][number];
type RepairLineView = RepairLine & { returnedQuantity: number; pendingQuantity: number };
type RepairProductGroup = { productName: string; specCount: number; pendingQuantity: number; expanded: boolean; lines: RepairLineView[] };

function previewReturnedQuantity(repairId: string, lineIndex: number): number {
  if (repairId === "preview-repair-2") return [220, 200][lineIndex] ?? 0;
  return 0;
}

function productGroups(repair: Repair, previewMode: boolean): RepairProductGroup[] {
  const groups = new Map<string, RepairLineView[]>();
  repair.lines.forEach((line, index) => {
    const returnedQuantity = previewMode ? previewReturnedQuantity(repair.repairId, index) : 0;
    const view = { ...line, returnedQuantity, pendingQuantity: Math.max(0, line.warehouseReturnQuantity - returnedQuantity) };
    groups.set(line.productName, [...(groups.get(line.productName) ?? []), view]);
  });
  return Array.from(groups.entries()).map(([productName, lines]) => ({
    productName,
    specCount: lines.length,
    pendingQuantity: lines.reduce((total, line) => total + line.pendingQuantity, 0),
    expanded: false,
    lines,
  }));
}

Page({
  data: { repair: null as Repair | null, loading: true, progress: 0, pending: 0, returnDateText: "", previewMode: false, productGroups: [] as RepairProductGroup[] },
  onLoad(options: Record<string, string | undefined>) { const previewMode = isDevPreview(options); this.setData({ previewMode }); if (options.repairId) void this.load(options.repairId, previewMode); },
  async load(repairId: string, previewMode = false) {
    try {
      const repair = previewMode ? previewRepair(repairId) : await repairApi.factoryGet(repairId);
      if (!repair) throw new Error("返修演示数据不存在");
      const progress = repair.warehouseReturnQuantity ? Math.round(repair.returnedQuantity / repair.warehouseReturnQuantity * 100) : 0;
      const [, month = "", day = ""] = repair.returnDate.split("-");
      this.setData({ repair, progress, pending: Math.max(0, repair.warehouseReturnQuantity - repair.returnedQuantity), returnDateText: `${month}月${day}日`, productGroups: productGroups(repair, previewMode) });
    } catch { wx.showToast({ title: "返修任务加载失败", icon: "none" }); }
    finally { this.setData({ loading: false }); }
  },
  async download() {
    if (!this.data.repair) return;
    if (this.data.previewMode) { wx.showToast({ title: "演示模式不下载附件", icon: "none" }); return; }
    try {
      const path = await repairApi.download(this.data.repair.originalFileId);
      wx.openDocument({ filePath: path, showMenu: true });
    } catch { wx.showToast({ title: "质检附件下载失败", icon: "none" }); }
  },
  toggleProduct(event: WechatMiniprogram.TouchEvent) {
    const index = Number(event.currentTarget.dataset.index);
    this.setData({ [`productGroups[${index}].expanded`]: !this.data.productGroups[index]?.expanded });
  },
  previewReturn() { wx.showToast({ title: "S10 发回流程演示", icon: "none" }); },
  goBack() { wx.navigateBack(); },
});
