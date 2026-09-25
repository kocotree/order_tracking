import { PagedList } from "../../modules/lists/paged-list";
import { shipmentApi, type AdminShipmentSummary, type Shipment } from "../../api/shipments";
import { repairApi, type RepairSummary } from "../../api/repairs";
import { factoryApi } from "../../api/factory";
import { isDevPreview, PREVIEW_ADMIN_REPAIRS, PREVIEW_FACTORY_SHIPMENTS } from "../../modules/dev-preview";
import { adminNavigationItems } from "../../modules/navigation";

type ShipmentCard = AdminShipmentSummary & { productSummary: string; orderSummary: string };
type FilterOption = { label: string; value: string };
type RepairCard = RepairSummary & { progress: number; pending: number };

function summarize(productNames: string, orderNos: string): { productSummary: string; orderSummary: string } {
  const names = productNames.split("、").filter(Boolean);
  return {
    productSummary: names.length > 1 ? `${names[0]}等${names.length}个产品` : (names[0] || "—"),
    orderSummary: orderNos || "—",
  };
}

function toCard(item: AdminShipmentSummary): ShipmentCard {
  return { ...item, ...summarize(item.productNames, item.orderNos) };
}

// 预览数据是完整发货单快照，需先折算成列表接口的摘要字段
function previewCard(shipment: Shipment): ShipmentCard {
  const productNames = Array.from(new Set(shipment.lines.map((line) => line.productName)));
  const orderNos = Array.from(new Set(shipment.lines.map((line) => line.orderNo)));
  return {
    ...shipment,
    receiptStatus: "UNRECEIVED",
    businessDate: shipment.businessDate,
    productNames: productNames.join("、"),
    orderNos: orderNos.join("、"),
    ...summarize(productNames.join("、"), orderNos.join("、")),
  };
}

function toRepairCard(item: RepairSummary): RepairCard {
  return {
    ...item,
    progress: item.warehouseReturnQuantity ? Math.round(item.returnedQuantity / item.warehouseReturnQuantity * 100) : 0,
    pending: Math.max(0, item.warehouseReturnQuantity - item.returnedQuantity),
  };
}

function optionIndex(options: FilterOption[], value: string): number {
  const index = options.findIndex((item) => item.value === value);
  return index < 0 ? 0 : index;
}

Page({
  pager: null as PagedList<ShipmentCard> | null,
  repairPager: null as PagedList<RepairCard> | null,
  data: {
    activeTab: "shipments", previewMode: false, keyword: "", filterOpen: false,
    items: [] as ShipmentCard[], total: 0, loading: true, loadingMore: false, hasMore: false, error: "",
    repairItems: [] as RepairCard[], repairTotal: 0, repairLoading: true, repairLoadingMore: false, repairHasMore: false, repairError: "",
    repairStatus: "all", repairFactoryCount: 0, repairFactory: "", repairPeriod: "",
    factory: "", shipDateFrom: "", shipDateTo: "", activeFilterCount: 0, repairFilterCount: 0,
    periodOptions: ["全部周期"], draftPeriodIndex: 0,
    factoryOptions: [{ label: "全部工厂", value: "" }] as FilterOption[],
    repairStatusOptions: ["全部状态", "未完成", "已完成"],
    draftFactoryIndex: 0, draftShipDateFrom: "", draftShipDateTo: "", draftRepairStatus: "all",
    navigationItems: adminNavigationItems(),
  },
  onLoad(options: Record<string, string | undefined>) {
    this.setData({ previewMode: isDevPreview(options) });
    if (!this.data.previewMode) { void this.loadFactoryOptions(); void this.loadPeriodOptions(); }
  },
  onShow() { void this.load(); },
  onUnload() { this.pager?.dispose(); this.repairPager?.dispose(); },
  onReachBottom() { void (this.data.activeTab === "repairs" ? this.repairPager : this.pager)?.next(); },
  retry() { this.onReachBottom(); },
  onPullDownRefresh() { void this.load().finally(() => wx.stopPullDownRefresh()); },
  load() { return this.data.activeTab === "repairs" ? this.loadRepairs() : this.loadShipments(); },
  loadShipments() {
    if (!this.pager) this.pager = new PagedList(item => item.shipmentId, state => this.setData(state));
    const params = { keyword: this.data.keyword.trim(), factory: this.data.factory, dateFrom: this.data.shipDateFrom, dateTo: this.data.shipDateTo };
    return this.pager.reset(async (page) => {
      if (!this.data.previewMode) {
        const result = await shipmentApi.adminPage({ ...params, page });
        return { items: result.items.map(toCard), total: result.total };
      }
      const keyword = params.keyword.toLowerCase();
      const items = PREVIEW_FACTORY_SHIPMENTS.map(previewCard).filter((item) =>
        (!keyword || `${item.productSummary} ${item.orderSummary}`.toLowerCase().includes(keyword))
        && (!params.factory || item.factoryName === params.factory)
        && (!params.dateFrom || (item.businessDate || "") >= params.dateFrom)
        && (!params.dateTo || (item.businessDate || "") <= params.dateTo));
      return { items, total: items.length };
    });
  },
  loadRepairs() {
    if (!this.repairPager) {
      this.repairPager = new PagedList(item => item.repairId, state => this.setData({
        repairItems: state.items, repairTotal: state.total, repairLoading: state.loading,
        repairLoadingMore: state.loadingMore, repairHasMore: state.hasMore, repairError: state.error,
      }));
    }
    const params = { keyword: this.data.keyword.trim(), status: this.data.repairStatus === "all" ? "" : this.data.repairStatus, factories: this.data.repairFactory, period: this.data.repairPeriod };
    return this.repairPager.reset(async (page) => {
      if (!this.data.previewMode) {
        const result = await repairApi.adminPage({ ...params, status: params.status || "all", page });
        this.setData({ repairFactoryCount: result.factoryCount });
        return { items: result.items.map(toRepairCard), total: result.total };
      }
      const keyword = params.keyword.toLowerCase();
      const items = PREVIEW_ADMIN_REPAIRS.map(toRepairCard).filter((item: RepairCard) =>
        (!keyword || item.factoryName.toLowerCase().includes(keyword))
        && (!params.status || item.status === params.status)
        && (!params.factories || item.factoryName === params.factories)
        && (!params.period || item.repairNo === params.period));
      this.setData({ repairFactoryCount: new Set(items.map((item: RepairCard) => item.factoryId)).size });
      return { items, total: items.length };
    });
  },
  async loadFactoryOptions() {
    const result = await factoryApi.listFactories();
    this.setData({ factoryOptions: [{ label: "全部工厂", value: "" }, ...result.items.map((item) => ({ label: item.factoryName, value: item.factoryName }))] });
  },
  async loadPeriodOptions() {
    this.setData({ periodOptions: ["全部周期", ...(await repairApi.adminPeriodOptions()).items] });
  },
  selectTab(event: WechatMiniprogram.TouchEvent) {
    this.setData({ activeTab: String(event.currentTarget.dataset.tab), keyword: "", filterOpen: false }, () => {
      wx.pageScrollTo({ scrollTop: 0, duration: 0 });
      void this.load();
    });
  },
  keywordChanged(event: WechatMiniprogram.Input) {
    this.setData({ keyword: event.detail.value });
    void this.load();
  },
  toggleFilter() {
    if (this.data.filterOpen) { this.closeFilter(); return; }
    this.setData({
      filterOpen: true,
      draftFactoryIndex: optionIndex(this.data.factoryOptions, this.data.activeTab === "repairs" ? this.data.repairFactory : this.data.factory),
      draftShipDateFrom: this.data.shipDateFrom,
      draftShipDateTo: this.data.shipDateTo,
      draftRepairStatus: this.data.repairStatus,
      draftPeriodIndex: Math.max(0, this.data.periodOptions.indexOf(this.data.repairPeriod)),
    });
  },
  closeFilter() { this.setData({ filterOpen: false }); },
  stopPropagation() {},
  factoryChanged(event: WechatMiniprogram.PickerChange) { this.setData({ draftFactoryIndex: Number(event.detail.value) }); },
  shipDateFromChanged(event: WechatMiniprogram.PickerChange) { this.setData({ draftShipDateFrom: String(event.detail.value) }); },
  shipDateToChanged(event: WechatMiniprogram.PickerChange) { this.setData({ draftShipDateTo: String(event.detail.value) }); },
  repairStatusChanged(event: WechatMiniprogram.PickerChange) { this.setData({ draftRepairStatus: ["all", "INCOMPLETE", "COMPLETED"][Number(event.detail.value)] || "all" }); },
  periodChanged(event: WechatMiniprogram.PickerChange) { this.setData({ draftPeriodIndex: Number(event.detail.value) }); },
  resetFilter() { this.setData({ draftFactoryIndex: 0, draftShipDateFrom: "", draftShipDateTo: "", draftRepairStatus: "all", draftPeriodIndex: 0 }); },
  applyFilter() {
    if (this.data.activeTab !== "repairs" && this.data.draftShipDateFrom && this.data.draftShipDateTo && this.data.draftShipDateFrom > this.data.draftShipDateTo) {
      wx.showToast({ title: "开始日期不能晚于结束日期", icon: "none" });
      return;
    }
    const selectedFactory = this.data.factoryOptions[this.data.draftFactoryIndex]?.value ?? "";
    if (this.data.activeTab === "repairs") {
      const repairFilterCount = [this.data.draftRepairStatus !== "all", Boolean(selectedFactory), this.data.draftPeriodIndex > 0].filter(Boolean).length;
      this.setData({ repairStatus: this.data.draftRepairStatus, repairFactory: selectedFactory, repairPeriod: this.data.draftPeriodIndex ? this.data.periodOptions[this.data.draftPeriodIndex] : "", repairFilterCount, filterOpen: false }, () => {
        wx.pageScrollTo({ scrollTop: 0, duration: 0 });
        void this.loadRepairs();
      });
      return;
    }
    const activeFilterCount = [Boolean(selectedFactory), Boolean(this.data.draftShipDateFrom), Boolean(this.data.draftShipDateTo)].filter(Boolean).length;
    this.setData({ factory: selectedFactory, shipDateFrom: this.data.draftShipDateFrom, shipDateTo: this.data.draftShipDateTo, activeFilterCount, filterOpen: false }, () => {
      wx.pageScrollTo({ scrollTop: 0, duration: 0 });
      void this.loadShipments();
    });
  },
  open(event: WechatMiniprogram.TouchEvent) {
    wx.navigateTo({ url: `/pages/admin-shipment-detail/admin-shipment-detail?shipmentId=${encodeURIComponent(event.currentTarget.dataset.id)}${this.data.previewMode ? "&preview=1" : ""}` });
  },
  openRepair(event: WechatMiniprogram.TouchEvent) { wx.navigateTo({ url: `/pages/admin-repair-detail/admin-repair-detail?repairId=${encodeURIComponent(event.currentTarget.dataset.id)}${this.data.previewMode ? "&preview=1" : ""}` }); },
});
