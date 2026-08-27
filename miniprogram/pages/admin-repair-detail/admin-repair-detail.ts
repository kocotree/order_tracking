import { repairApi, type Repair, type RepairReturnBatch, type RepairReturnLine } from "../../api/repairs";
import { isDevPreview, previewAdminRepair } from "../../modules/dev-preview";

type ReturnLineView = RepairReturnLine & { returnedQuantity: number };
type ReturnBatchView = Omit<RepairReturnBatch, "lines"> & { expanded: boolean; returnedQuantity: number; lines: ReturnLineView[] };

function fileSize(bytes: number): string {
  if (!bytes) return "原始文件";
  return `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

function batchViews(repair: Repair): ReturnBatchView[] {
  return (repair.returnBatches ?? []).map((batch) => {
    const lines = batch.lines.map((line) => ({ ...line, returnedQuantity: line.repairedQuantity + line.scrappedQuantity }));
    return { ...batch, lines, expanded: false, returnedQuantity: lines.reduce((total, line) => total + line.returnedQuantity, 0) };
  });
}

Page({
  data: {
    repair: null as Repair | null,
    loading: true,
    progress: 0,
    pending: 0,
    previewMode: false,
    fileSizeText: "",
    returnBatches: [] as ReturnBatchView[],
  },
  onLoad(options: Record<string, string | undefined>) {
    const previewMode = isDevPreview(options);
    this.setData({ previewMode });
    if (options.repairId) void this.load(options.repairId, previewMode);
  },
  async load(repairId: string, previewMode = false) {
    try {
      const repair = previewMode ? previewAdminRepair(repairId) : await repairApi.adminGet(repairId);
      if (!repair) throw new Error("返修演示数据不存在");
      const progress = repair.warehouseReturnQuantity ? Math.round(repair.returnedQuantity / repair.warehouseReturnQuantity * 100) : 0;
      this.setData({
        repair,
        progress,
        pending: Math.max(0, repair.warehouseReturnQuantity - repair.returnedQuantity),
        fileSizeText: fileSize(repair.originalSizeBytes),
        returnBatches: batchViews(repair),
      });
    } catch { wx.showToast({ title: "返修详情加载失败", icon: "none" }); }
    finally { this.setData({ loading: false }); }
  },
  async openAttachment() {
    if (!this.data.repair) return;
    if (this.data.previewMode) { wx.showToast({ title: "演示模式不下载附件", icon: "none" }); return; }
    try {
      const path = await repairApi.download(this.data.repair.originalFileId);
      wx.openDocument({ filePath: path, showMenu: true });
    } catch { wx.showToast({ title: "质检附件打开失败", icon: "none" }); }
  },
  toggleBatch(event: WechatMiniprogram.TouchEvent) {
    const index = Number(event.currentTarget.dataset.index);
    this.setData({ [`returnBatches[${index}].expanded`]: !this.data.returnBatches[index]?.expanded });
  },
  goBack() { wx.navigateBack(); },
});
