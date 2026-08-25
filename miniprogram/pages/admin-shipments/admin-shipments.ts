import { shipmentApi, type Shipment } from "../../api/shipments";
import { isDevPreview, PREVIEW_SHIPMENT } from "../../modules/dev-preview";

type ShipmentCard = Shipment & { productSummary: string; orderSummary: string };
type FilterOption = { label: string; value: string };

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
    allItems: [] as ShipmentCard[], items: [] as ShipmentCard[], keyword: "", loading: true, previewMode: false,
    factoryId: "", shipDateFrom: "", shipDateTo: "", activeFilterCount: 0, filterOpen: false,
    factoryOptions: [{ label: "全部工厂", value: "" }] as FilterOption[],
    draftFactoryIndex: 0, draftShipDateFrom: "", draftShipDateTo: "",
    navigationItems: [
      { key: "orders", label: "订单", path: "/pages/admin-orders/admin-orders", icon: "/assets/icons/admin-orders.svg", activeIcon: "/assets/icons/admin-orders-active.svg" },
      { key: "shipments", label: "发货", path: "/pages/admin-shipments/admin-shipments", icon: "/assets/icons/factory-shipments.svg", activeIcon: "/assets/icons/factory-shipments-active.svg" },
      { key: "profile", label: "我的", path: "/pages/profile/profile", icon: "/assets/icons/admin-profile.svg", activeIcon: "/assets/icons/admin-profile-active.svg" },
    ],
  },
  onLoad(options: Record<string, string | undefined>) {
    const previewMode = isDevPreview(options);
    this.setData({ previewMode });
    if (previewMode) this.setItems([PREVIEW_SHIPMENT]);
    else void this.load();
  },
  setItems(shipments: Shipment[]) {
    const allItems = shipments.map(toCard);
    const factories = Array.from(new Map(allItems.map((item) => [item.factoryId, item.factoryName])).entries());
    this.setData({
      allItems,
      factoryOptions: [{ label: "全部工厂", value: "" }, ...factories.map(([value, label]) => ({ label, value }))],
      loading: false,
    }, () => this.applyVisibleItems());
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
      draftFactoryIndex: optionIndex(this.data.factoryOptions, this.data.factoryId),
      draftShipDateFrom: this.data.shipDateFrom,
      draftShipDateTo: this.data.shipDateTo,
    });
  },
  closeFilter() { this.setData({ filterOpen: false }); },
  stopPropagation() {},
  factoryChanged(event: WechatMiniprogram.PickerChange) { this.setData({ draftFactoryIndex: Number(event.detail.value) }); },
  shipDateFromChanged(event: WechatMiniprogram.PickerChange) { this.setData({ draftShipDateFrom: String(event.detail.value) }); },
  shipDateToChanged(event: WechatMiniprogram.PickerChange) { this.setData({ draftShipDateTo: String(event.detail.value) }); },
  resetFilter() { this.setData({ draftFactoryIndex: 0, draftShipDateFrom: "", draftShipDateTo: "" }); },
  applyFilter() {
    if (this.data.draftShipDateFrom && this.data.draftShipDateTo && this.data.draftShipDateFrom > this.data.draftShipDateTo) {
      wx.showToast({ title: "开始日期不能晚于结束日期", icon: "none" });
      return;
    }
    const values = {
      factoryId: this.data.factoryOptions[this.data.draftFactoryIndex]?.value ?? "",
      shipDateFrom: this.data.draftShipDateFrom,
      shipDateTo: this.data.draftShipDateTo,
    };
    const activeFilterCount = [Boolean(values.factoryId), Boolean(values.shipDateFrom), Boolean(values.shipDateTo)].filter(Boolean).length;
    this.setData({ ...values, activeFilterCount, filterOpen: false }, () => this.applyVisibleItems());
  },
  open(event: WechatMiniprogram.TouchEvent) {
    wx.navigateTo({ url: `/pages/admin-shipment-detail/admin-shipment-detail?shipmentId=${encodeURIComponent(event.currentTarget.dataset.id)}${this.data.previewMode ? "&preview=1" : ""}` });
  },
});
