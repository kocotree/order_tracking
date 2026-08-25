import { shipmentApi, type Shipment } from "../../api/shipments";
import { isDevPreview, PREVIEW_FACTORY_SHIPMENTS } from "../../modules/dev-preview";

type ShipmentCard = Shipment & { productSummary: string; orderSummary: string };

function toCard(item: Shipment): ShipmentCard {
  const productNames = Array.from(new Set(item.lines.map((line) => line.productName)));
  const orderNos = Array.from(new Set(item.lines.map((line) => line.orderNo)));
  return {
    ...item,
    productSummary: productNames.length > 1 ? `${productNames[0]}等${productNames.length}个产品` : (productNames[0] || "—"),
    orderSummary: orderNos.join("、"),
  };
}

Page({
  data: {
    allItems: [] as ShipmentCard[], items: [] as ShipmentCard[], keyword: "", loading: true, previewMode: false,
    filterOpen: false, shipDateFrom: "", shipDateTo: "", draftShipDateFrom: "", draftShipDateTo: "", filterCount: 0,
    navigationItems: [
      { key: "primary", label: "任务", path: "/pages/factory-tasks/factory-tasks", icon: "/assets/icons/admin-orders.svg", activeIcon: "/assets/icons/admin-orders-active.svg" },
      { key: "shipments", label: "发货记录", path: "/pages/factory-shipments/factory-shipments", icon: "/assets/icons/factory-shipments.svg", activeIcon: "/assets/icons/factory-shipments-active.svg" },
      { key: "profile", label: "我的", path: "/pages/profile/profile", icon: "/assets/icons/admin-profile.svg", activeIcon: "/assets/icons/admin-profile-active.svg" },
    ],
  },

  onLoad(options: Record<string, string | undefined>) {
    const previewMode = isDevPreview(options);
    this.setData({ previewMode });
    if (previewMode) {
      const allItems = PREVIEW_FACTORY_SHIPMENTS.map(toCard);
      this.setData({ allItems, items: allItems, loading: false });
    } else void this.load();
  },

  async load() {
    try {
      const allItems = (await shipmentApi.factoryList()).items.map(toCard);
      this.setData({ allItems });
      this.applyLocalFilters();
    } catch { wx.showToast({ title: "发货记录加载失败", icon: "none" }); }
    finally { this.setData({ loading: false }); }
  },

  applyLocalFilters() {
    const keyword = this.data.keyword.trim().toLowerCase();
    const items = this.data.allItems.filter((item) => {
      const searchable = `${item.productSummary} ${item.orderSummary}`.toLowerCase();
      return (!keyword || searchable.includes(keyword))
        && (!this.data.shipDateFrom || (item.businessDate || "") >= this.data.shipDateFrom)
        && (!this.data.shipDateTo || (item.businessDate || "") <= this.data.shipDateTo);
    });
    this.setData({ items, filterCount: Number(Boolean(this.data.shipDateFrom || this.data.shipDateTo)) });
  },

  keywordChanged(event: WechatMiniprogram.Input) { this.setData({ keyword: event.detail.value }); this.applyLocalFilters(); },
  openFilter() { this.setData({ filterOpen: true, draftShipDateFrom: this.data.shipDateFrom, draftShipDateTo: this.data.shipDateTo }); },
  closeFilter() { this.setData({ filterOpen: false }); },
  stopPropagation() {},
  shipDateFromChanged(event: WechatMiniprogram.PickerChange) { this.setData({ draftShipDateFrom: String(event.detail.value) }); },
  shipDateToChanged(event: WechatMiniprogram.PickerChange) { this.setData({ draftShipDateTo: String(event.detail.value) }); },
  resetFilter() { this.setData({ draftShipDateFrom: "", draftShipDateTo: "" }); },
  applyFilter() { this.setData({ shipDateFrom: this.data.draftShipDateFrom, shipDateTo: this.data.draftShipDateTo, filterOpen: false }); this.applyLocalFilters(); },
  clearFilters() { this.setData({ keyword: "", shipDateFrom: "", shipDateTo: "", draftShipDateFrom: "", draftShipDateTo: "" }); this.applyLocalFilters(); },
  open(event: WechatMiniprogram.TouchEvent) { wx.navigateTo({ url: `/pages/factory-shipment-detail/factory-shipment-detail?shipmentId=${encodeURIComponent(event.currentTarget.dataset.id)}${this.data.previewMode ? "&preview=1" : ""}` }); },
});
