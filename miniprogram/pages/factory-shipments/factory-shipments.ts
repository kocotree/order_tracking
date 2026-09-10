import { PagedList } from "../../modules/lists/paged-list";
import { factoryRevision } from "../../modules/lists/factory-revisions";
import { shipmentApi, type Shipment, type FactoryShipmentSummary } from "../../api/shipments";
import { isDevPreview, PREVIEW_FACTORY_SHIPMENTS } from "../../modules/dev-preview";

type ShipmentCard = FactoryShipmentSummary;

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
  pager: null as PagedList<ShipmentCard> | null,
  revision: -1,
  data: {
    total:0, loadingMore:false, hasMore:false, error:"", items: [] as ShipmentCard[], keyword: "", loading: true, previewMode: false,
    filterOpen: false, shipDateFrom: "", shipDateTo: "", draftShipDateFrom: "", draftShipDateTo: "", filterCount: 0,
    navigationItems: [
      { key: "primary", label: "任务", path: "/pages/factory-tasks/factory-tasks", icon: "/assets/icons/admin-orders.svg", activeIcon: "/assets/icons/admin-orders-active.svg" },
      { key: "shipments", label: "发货记录", path: "/pages/factory-shipments/factory-shipments", icon: "/assets/icons/factory-shipments.svg", activeIcon: "/assets/icons/factory-shipments-active.svg" },
      { key: "profile", label: "我的", path: "/pages/profile/profile", icon: "/assets/icons/admin-profile.svg", activeIcon: "/assets/icons/admin-profile-active.svg" },
    ],
  },

  onShow() {
    if(this.revision !== factoryRevision("shipments")) { void this.load(); wx.pageScrollTo({scrollTop:0,duration:0}); }
  },
  onLoad(options: Record<string, string | undefined>) { this.setData({previewMode:isDevPreview(options)}); void this.load(); },
  onUnload() { this.pager?.dispose(); },
  onReachBottom() { void this.pager?.next(); },
  retry() { this.onReachBottom(); },
  onPullDownRefresh() { void this.load().finally(()=>wx.stopPullDownRefresh()); },
  async load() {
    this.revision=factoryRevision("shipments");
    if(!this.pager) this.pager=new PagedList(item=>item.shipmentId,state=>this.setData(state));
    const params={keyword:this.data.keyword,shipDateFrom:this.data.shipDateFrom||undefined,shipDateTo:this.data.shipDateTo||undefined};
    await this.pager.reset(async page=> {
      if(!this.data.previewMode) return shipmentApi.factoryPage({...params,page});
      const keyword=params.keyword.trim().toLowerCase();
      const items=PREVIEW_FACTORY_SHIPMENTS.map(toCard).filter(item=>(!keyword || `${item.productSummary} ${item.orderSummary}`.toLowerCase().includes(keyword))&&(!params.shipDateFrom || (item.businessDate||"")>=params.shipDateFrom)&&(!params.shipDateTo || (item.businessDate||"")<=params.shipDateTo));
      return {items,total:items.length};
    });
  },
  applyLocalFilters() {
    this.setData({filterCount:Number(Boolean(this.data.shipDateFrom||this.data.shipDateTo))});
    wx.pageScrollTo({scrollTop:0,duration:0}); void this.load();
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
