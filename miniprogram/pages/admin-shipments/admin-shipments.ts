import { shipmentApi, type Shipment } from "../../api/shipments";
import { repairApi, type Repair } from "../../api/repairs";
import { isDevPreview, PREVIEW_ADMIN_REPAIRS, PREVIEW_FACTORY_SHIPMENTS } from "../../modules/dev-preview";

type ShipmentCard = Shipment & { productSummary: string; orderSummary: string };
type FilterOption = { label: string; value: string };
type RepairCard = Repair & { productSummary: string; progress: number; pending: number };

function toCard(shipment: Shipment): ShipmentCard {
  const productNames = Array.from(new Set(shipment.lines.map((line) => line.productName)));
  const orderNos = Array.from(new Set(shipment.lines.map((line) => line.orderNo)));
  return {
    ...shipment,
    productSummary: productNames.length > 1 ? `${productNames[0]}等${productNames.length}个产品` : (productNames[0] || "—"),
    orderSummary: orderNos.join("、") || "—",
  };
}

function optionIndex(options: FilterOption[], value: string): number {
  const index = options.findIndex((item) => item.value === value);
  return index < 0 ? 0 : index;
}

Page({
  data: {
    activeTab: "shipments", repairItems: [] as RepairCard[], allRepairItems: [] as RepairCard[], repairStatus: "all", repairFactoryCount: 0,
    allItems: [] as ShipmentCard[], items: [] as ShipmentCard[], keyword: "", loading: true, previewMode: false,
    factoryId: "", shipDateFrom: "", shipDateTo: "", activeFilterCount: 0, filterOpen: false,
    repairFactoryId: "", repairDateFrom: "", repairDateTo: "", repairFilterCount: 0,
    factoryOptions: [{ label: "全部工厂", value: "" }] as FilterOption[],
    repairStatusOptions: ["全部状态", "未完成", "已完成"],
    draftFactoryIndex: 0, draftShipDateFrom: "", draftShipDateTo: "", draftRepairStatus: "all",
    navigationItems: [
      { key: "orders", label: "订单", path: "/pages/admin-orders/admin-orders", icon: "/assets/icons/admin-orders.svg", activeIcon: "/assets/icons/admin-orders-active.svg" },
      { key: "shipments", label: "发货", path: "/pages/admin-shipments/admin-shipments", icon: "/assets/icons/factory-shipments.svg", activeIcon: "/assets/icons/factory-shipments-active.svg" },
      { key: "profile", label: "我的", path: "/pages/profile/profile", icon: "/assets/icons/admin-profile.svg", activeIcon: "/assets/icons/admin-profile-active.svg" },
    ],
  },
  onLoad(options: Record<string, string | undefined>) {
    const previewMode = isDevPreview(options);
    this.setData({ previewMode });
    if (previewMode) { this.setItems(PREVIEW_FACTORY_SHIPMENTS); this.setRepairs(PREVIEW_ADMIN_REPAIRS); }
    else { void this.load(); void this.loadRepairs(); }
  },
  selectTab(event: WechatMiniprogram.TouchEvent) {
    this.setData({ activeTab: String(event.currentTarget.dataset.tab), keyword: "", filterOpen: false }, () => {
      this.refreshFactoryOptions();
      this.applyVisibleItems();
    });
  },
  async loadRepairs() {
    try {
      this.setRepairs((await repairApi.adminList()).items);
    } catch { wx.showToast({ title: "返修进度加载失败", icon: "none" }); }
  },
  setRepairs(repairs: Repair[]) {
    const allRepairItems = repairs.map((item) => ({ ...item, productSummary: Array.from(new Set(item.lines.map((line) => line.productName))).join("、") || "—", progress: item.warehouseReturnQuantity ? Math.round(item.returnedQuantity / item.warehouseReturnQuantity * 100) : 0, pending: Math.max(0, item.warehouseReturnQuantity - item.returnedQuantity) }));
    this.setData({ allRepairItems }, () => { if (this.data.activeTab === "repairs") this.refreshFactoryOptions(); this.applyVisibleItems(); });
  },
  setItems(shipments: Shipment[]) {
    const allItems = shipments.map(toCard);
    this.setData({
      allItems,
      loading: false,
    }, () => { if (this.data.activeTab === "shipments") this.refreshFactoryOptions(); this.applyVisibleItems(); });
  },
  refreshFactoryOptions() {
    const source = this.data.activeTab === "repairs" ? this.data.allRepairItems : this.data.allItems;
    const factories = Array.from(new Map(source.map((item) => [item.factoryId, item.factoryName])).entries());
    this.setData({ factoryOptions: [{ label: "全部工厂", value: "" }, ...factories.map(([value, label]) => ({ label, value }))] });
  },
  async load() {
    try { this.setItems((await shipmentApi.adminList()).items); }
    catch { wx.showToast({ title: "发货单加载失败", icon: "none" }); this.setData({ loading: false }); }
  },
  keywordChanged(event: WechatMiniprogram.Input) {
    this.setData({ keyword: event.detail.value }, () => this.applyVisibleItems());
  },
  applyVisibleItems() {
    const keyword = this.data.keyword.trim().toLowerCase();
    if (this.data.activeTab === "repairs") {
      const repairItems = this.data.allRepairItems.filter((item) =>
        (!keyword || item.factoryName.toLowerCase().includes(keyword))
        && (this.data.repairStatus === "all" || item.status === this.data.repairStatus)
        && (!this.data.repairFactoryId || item.factoryId === this.data.repairFactoryId)
        && (!this.data.repairDateFrom || item.returnDate >= this.data.repairDateFrom)
        && (!this.data.repairDateTo || item.returnDate <= this.data.repairDateTo));
      this.setData({ repairItems, repairFactoryCount: new Set(repairItems.map((item) => item.factoryId)).size });
      return;
    }
    this.setData({
      items: this.data.allItems.filter((item) =>
        (!keyword || item.productSummary.toLowerCase().includes(keyword) || item.orderSummary.toLowerCase().includes(keyword))
        && (!this.data.factoryId || item.factoryId === this.data.factoryId)
        && (!this.data.shipDateFrom || Boolean(item.businessDate && item.businessDate >= this.data.shipDateFrom))
        && (!this.data.shipDateTo || Boolean(item.businessDate && item.businessDate <= this.data.shipDateTo))),
    });
  },
  toggleFilter() {
    if (this.data.filterOpen) { this.closeFilter(); return; }
    this.setData({
      filterOpen: true,
      draftFactoryIndex: optionIndex(this.data.factoryOptions, this.data.activeTab === "repairs" ? this.data.repairFactoryId : this.data.factoryId),
      draftShipDateFrom: this.data.activeTab === "repairs" ? this.data.repairDateFrom : this.data.shipDateFrom,
      draftShipDateTo: this.data.activeTab === "repairs" ? this.data.repairDateTo : this.data.shipDateTo,
      draftRepairStatus: this.data.repairStatus,
    });
  },
  closeFilter() { this.setData({ filterOpen: false }); },
  stopPropagation() {},
  factoryChanged(event: WechatMiniprogram.PickerChange) { this.setData({ draftFactoryIndex: Number(event.detail.value) }); },
  shipDateFromChanged(event: WechatMiniprogram.PickerChange) { this.setData({ draftShipDateFrom: String(event.detail.value) }); },
  shipDateToChanged(event: WechatMiniprogram.PickerChange) { this.setData({ draftShipDateTo: String(event.detail.value) }); },
  repairStatusChanged(event: WechatMiniprogram.PickerChange) { this.setData({ draftRepairStatus: ["all", "INCOMPLETE", "COMPLETED"][Number(event.detail.value)] || "all" }); },
  resetFilter() { this.setData({ draftFactoryIndex: 0, draftShipDateFrom: "", draftShipDateTo: "", draftRepairStatus: "all" }); },
  applyFilter() {
    if (this.data.draftShipDateFrom && this.data.draftShipDateTo && this.data.draftShipDateFrom > this.data.draftShipDateTo) {
      wx.showToast({ title: "开始日期不能晚于结束日期", icon: "none" });
      return;
    }
    const selectedFactoryId = this.data.factoryOptions[this.data.draftFactoryIndex]?.value ?? "";
    if (this.data.activeTab === "repairs") {
      const repairFilterCount = [this.data.draftRepairStatus !== "all", Boolean(selectedFactoryId), Boolean(this.data.draftShipDateFrom), Boolean(this.data.draftShipDateTo)].filter(Boolean).length;
      this.setData({ repairStatus: this.data.draftRepairStatus, repairFactoryId: selectedFactoryId, repairDateFrom: this.data.draftShipDateFrom, repairDateTo: this.data.draftShipDateTo, repairFilterCount, filterOpen: false }, () => this.applyVisibleItems());
      return;
    }
    const activeFilterCount = [Boolean(selectedFactoryId), Boolean(this.data.draftShipDateFrom), Boolean(this.data.draftShipDateTo)].filter(Boolean).length;
    this.setData({ factoryId: selectedFactoryId, shipDateFrom: this.data.draftShipDateFrom, shipDateTo: this.data.draftShipDateTo, activeFilterCount, filterOpen: false }, () => this.applyVisibleItems());
  },
  open(event: WechatMiniprogram.TouchEvent) {
    wx.navigateTo({ url: `/pages/admin-shipment-detail/admin-shipment-detail?shipmentId=${encodeURIComponent(event.currentTarget.dataset.id)}${this.data.previewMode ? "&preview=1" : ""}` });
  },
  openRepair(event: WechatMiniprogram.TouchEvent) { wx.navigateTo({ url: `/pages/admin-repair-detail/admin-repair-detail?repairId=${encodeURIComponent(event.currentTarget.dataset.id)}${this.data.previewMode ? "&preview=1" : ""}` }); },
});
