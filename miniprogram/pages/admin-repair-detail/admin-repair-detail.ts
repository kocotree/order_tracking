import { repairApi, type Repair } from "../../api/repairs";

Page({
  data: { repair: null as Repair | null, loading: true, progress: 0, pending: 0 },
  onLoad(options: Record<string, string | undefined>) { if (options.repairId) void this.load(options.repairId); },
  async load(repairId: string) {
    try {
      const repair = await repairApi.adminGet(repairId);
      const progress = repair.warehouseReturnQuantity ? Math.round(repair.returnedQuantity / repair.warehouseReturnQuantity * 100) : 0;
      this.setData({ repair, progress, pending: Math.max(0, repair.warehouseReturnQuantity - repair.returnedQuantity) });
    } catch { wx.showToast({ title: "返修详情加载失败", icon: "none" }); }
    finally { this.setData({ loading: false }); }
  },
  goBack() { wx.navigateBack(); },
});
