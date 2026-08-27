import { repairApi, type Repair } from "../../api/repairs";

Page({
  data: { repair: null as Repair | null, loading: true, progress: 0, pending: 0 },
  onLoad(options: Record<string, string | undefined>) { if (options.repairId) void this.load(options.repairId); },
  async load(repairId: string) {
    try {
      const repair = await repairApi.factoryGet(repairId);
      const progress = repair.warehouseReturnQuantity ? Math.round(repair.returnedQuantity / repair.warehouseReturnQuantity * 100) : 0;
      this.setData({ repair, progress, pending: Math.max(0, repair.warehouseReturnQuantity - repair.returnedQuantity) });
    } catch { wx.showToast({ title: "返修任务加载失败", icon: "none" }); }
    finally { this.setData({ loading: false }); }
  },
  async download() {
    if (!this.data.repair) return;
    try {
      const path = await repairApi.download(this.data.repair.originalFileId);
      wx.openDocument({ filePath: path, showMenu: true });
    } catch { wx.showToast({ title: "质检附件下载失败", icon: "none" }); }
  },
  goBack() { wx.navigateBack(); },
});
