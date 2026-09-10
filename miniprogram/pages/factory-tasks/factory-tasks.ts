import { PagedList } from "../../modules/lists/paged-list";
import { factoryRevision } from "../../modules/lists/factory-revisions";
import { orderApi, type Order } from "../../api/orders";
import { repairApi, type RepairSummary } from "../../api/repairs";
import { isDevPreview, PREVIEW_REPAIRS, previewOrder } from "../../modules/dev-preview";
import { clearSession, storedUser } from "../../modules/identity/session";
import { formatContractShipDate, formatQuantity, orderProductSummary, statusTone } from "../../modules/orders/format";

type FilterOption = { label: string; value: string };
type ViewOrder = Order & {
  productSummary: string;
  contractShipDateText: string;
  totalText: string;
  shippedText: string;
  pendingText: string;
  statusTone: string;
};
type RepairCard = RepairSummary & { productSummary: string; progress: number; pending: number; returnDateText: string };

const statusOptions: FilterOption[] = [
  { label: "全部状态", value: "all" },
  { label: "未完成", value: "未完成" },
  { label: "已逾期", value: "已逾期" },
  { label: "已完成", value: "已完成" },
];

const repairStatusOptions: FilterOption[] = [
  { label: "全部状态", value: "all" },
  { label: "未完成", value: "INCOMPLETE" },
  { label: "已完成", value: "COMPLETED" },
];

function formatRepairDate(value: string): string {
  return value.slice(0, 10);
}

function optionIndex(options: FilterOption[], value: string): number {
  const index = options.findIndex((option) => option.value === value);
  return index < 0 ? 0 : index;
}

function countFilters(values: { status: string; shipDateFrom: string; shipDateTo: string }): number {
  return [values.status !== "all", Boolean(values.shipDateFrom), Boolean(values.shipDateTo)].filter(Boolean).length;
}

Page({
  ordersPager: null as PagedList<ViewOrder> | null,
  repairsPager: null as PagedList<RepairCard> | null,
  initialized: false,
  ordersRevision: -1,
  repairsRevision: -1,
  data: {
    activeTab: "orders",
    items: [] as ViewOrder[],
    repairItems: [] as RepairCard[], repairStatus: "all",
    repairStatusOptions,
    draftRepairStatusIndex: 0,
    repairActiveFilterCount: 0,
    keyword: "",
    status: "all",
    shipDateFrom: "",
    shipDateTo: "",
    statusOptions,
    draftStatusIndex: 0,
    draftShipDateFrom: "",
    draftShipDateTo: "",
    activeFilterCount: 0,
    filterOpen: false,
    total: 0, loadingMore: false, hasMore: false,
    loading: true,
    error: "",
    previewMode: false,
    navigationItems: [
      { key: "primary", label: "任务", path: "/pages/factory-tasks/factory-tasks", icon: "/assets/icons/admin-orders.svg", activeIcon: "/assets/icons/admin-orders-active.svg" },
      { key: "shipments", label: "发货记录", path: "/pages/factory-shipments/factory-shipments", icon: "/assets/icons/factory-shipments.svg", activeIcon: "/assets/icons/factory-shipments-active.svg" },
      { key: "profile", label: "我的", path: "/pages/profile/profile", icon: "/assets/icons/admin-profile.svg", activeIcon: "/assets/icons/admin-profile-active.svg" },
    ],
  },
  onLoad(options: Record<string, string | undefined>) {
    const previewMode = isDevPreview(options);
    if (!previewMode && storedUser()?.role !== "factory") {
      clearSession();
      wx.reLaunch({ url: "/pages/auth/auth" });
      return;
    }
    this.initialized = true;
    this.setData({ previewMode });
    void this.loadOrders();
  },
  onShow() {
    if (!this.initialized) return;
    const repairs = this.data.activeTab === "repairs";
    if ((repairs ? this.repairsRevision : this.ordersRevision) !== factoryRevision(repairs ? "repairs" : "orders")) {
      if (repairs) void this.loadRepairs(); else void this.loadOrders();
      wx.pageScrollTo({scrollTop:0,duration:0});
    }
  },
  onUnload() { this.ordersPager?.dispose(); this.repairsPager?.dispose(); },
  onReachBottom() { void (this.data.activeTab === "repairs" ? this.repairsPager : this.ordersPager)?.next(); },
  retry() { this.onReachBottom(); },
  onPullDownRefresh() {
    const request = this.data.activeTab === "repairs" ? this.loadRepairs() : this.loadOrders();
    void request.finally(() => wx.stopPullDownRefresh());
  },
  selectTab(event: WechatMiniprogram.TouchEvent) {
    const activeTab = String(event.currentTarget.dataset.tab);
    if (activeTab === this.data.activeTab) return;
    this.ordersPager?.dispose(); this.repairsPager?.dispose();
    this.setData({ activeTab, keyword: "", filterOpen: false });
    wx.pageScrollTo({scrollTop:0,duration:0});
    if (activeTab === "repairs") void this.loadRepairs(); else void this.loadOrders();
  },
  keywordChanged(event: WechatMiniprogram.Input) { this.setData({ keyword: event.detail.value }); if (this.data.activeTab === "repairs") this.applyRepairFilters(); },
  search() { wx.pageScrollTo({scrollTop:0,duration:0}); if (this.data.activeTab === "repairs") this.applyRepairFilters(); else void this.loadOrders(); },
  async loadRepairs() {
    this.repairsRevision = factoryRevision("repairs");
    if (!this.repairsPager) this.repairsPager = new PagedList(item => item.repairId, state => {
      if (this.data.activeTab === "repairs") { const {items, ...rest}=state; this.setData({...rest,repairItems:items}); }
    });
    const keyword=this.data.keyword, status=this.data.repairStatus;
    await this.repairsPager.reset(async page => {
      const result=this.data.previewMode ? {items:PREVIEW_REPAIRS.filter(item=>(!keyword.trim() || item.repairNo.toLowerCase().includes(keyword.trim().toLowerCase())) && (status === "all" || item.status === status)),total:0} : await repairApi.factoryPage({keyword,status,page});
      if(this.data.previewMode) result.total=result.items.length;
      return {total:result.total,items:result.items.map(item=>({...item,productSummary:"",progress:item.warehouseReturnQuantity ? Math.round(item.returnedQuantity/item.warehouseReturnQuantity*100):0,pending:Math.max(0,item.warehouseReturnQuantity-item.returnedQuantity),returnDateText:formatRepairDate(item.returnDate)}))};
    });
  },
  applyRepairFilters() { wx.pageScrollTo({scrollTop:0,duration:0}); void this.loadRepairs(); },
  setRepairStatus(event: WechatMiniprogram.TouchEvent) { this.setData({ repairStatus: String(event.currentTarget.dataset.status) }, () => this.applyRepairFilters()); },
  openRepair(event: WechatMiniprogram.TouchEvent) { wx.navigateTo({ url: `/pages/factory-repair-detail/factory-repair-detail?repairId=${encodeURIComponent(event.currentTarget.dataset.id)}${this.data.previewMode ? "&preview=1" : ""}` }); },
  toggleFilter() {
    if (this.data.filterOpen) { this.closeFilter(); return; }
    if (this.data.activeTab === "repairs") {
      this.setData({ filterOpen: true, draftRepairStatusIndex: optionIndex(this.data.repairStatusOptions, this.data.repairStatus) });
      return;
    }
    this.setData({
      filterOpen: true,
      draftStatusIndex: optionIndex(this.data.statusOptions, this.data.status),
      draftShipDateFrom: this.data.shipDateFrom,
      draftShipDateTo: this.data.shipDateTo,
    });
  },
  closeFilter() { this.setData({ filterOpen: false }); },
  stopPropagation() {},
  statusChanged(event: WechatMiniprogram.PickerChange) { this.setData({ draftStatusIndex: Number(event.detail.value) }); },
  shipDateFromChanged(event: WechatMiniprogram.PickerChange) { this.setData({ draftShipDateFrom: String(event.detail.value) }); },
  shipDateToChanged(event: WechatMiniprogram.PickerChange) { this.setData({ draftShipDateTo: String(event.detail.value) }); },
  repairStatusChanged(event: WechatMiniprogram.PickerChange) { this.setData({ draftRepairStatusIndex: Number(event.detail.value) }); },
  resetFilter() {
    if (this.data.activeTab === "repairs") { this.setData({ draftRepairStatusIndex: 0 }); return; }
    this.setData({ draftStatusIndex: 0, draftShipDateFrom: "", draftShipDateTo: "" });
  },
  applyFilter() {
    if (this.data.activeTab === "repairs") {
      const repairStatus = this.data.repairStatusOptions[this.data.draftRepairStatusIndex]?.value ?? "all";
      this.setData({ repairStatus, repairActiveFilterCount: repairStatus === "all" ? 0 : 1, filterOpen: false }, () => this.applyRepairFilters());
      return;
    }
    if (this.data.draftShipDateFrom && this.data.draftShipDateTo && this.data.draftShipDateFrom > this.data.draftShipDateTo) {
      wx.showToast({ title: "开始日期不能晚于结束日期", icon: "none" });
      return;
    }
    const values = {
      status: this.data.statusOptions[this.data.draftStatusIndex]?.value ?? "all",
      shipDateFrom: this.data.draftShipDateFrom,
      shipDateTo: this.data.draftShipDateTo,
    };
    this.setData({ ...values, activeFilterCount: countFilters(values), filterOpen: false }, () => { wx.pageScrollTo({scrollTop:0,duration:0}); void this.loadOrders(); });
  },
  async loadOrders() {
    this.ordersRevision = factoryRevision("orders");
    if (!this.ordersPager) this.ordersPager = new PagedList(item => item.orderId, state => {
      if (this.data.activeTab === "orders") this.setData(state);
    });
    const params = {keyword:this.data.keyword,status:this.data.status,shipDateFrom:this.data.shipDateFrom||undefined,shipDateTo:this.data.shipDateTo||undefined};
    await this.ordersPager.reset(async page => {
      if(this.data.previewMode) {
        const order=previewOrder(true), keyword=params.keyword.trim().toLowerCase();
        const matches=(!keyword || order.orderNo.toLowerCase().includes(keyword) || order.lines.some(line=>line.productName.toLowerCase().includes(keyword))) && (params.status==="all" || order.displayStatus===params.status) && (!(params.shipDateFrom || params.shipDateTo) || order.contractShipDates.some(value=>(!params.shipDateFrom || value>=params.shipDateFrom)&&(!params.shipDateTo || value<=params.shipDateTo)));
        return {items:matches?[this.toView(order)]:[],total:matches?1:0};
      }
      const result=await orderApi.list({...params,page,pageSize:20});
      return {items:result.items.map(item=>this.toView(item)),total:result.total};
    });
  },
  toView(item: Order): ViewOrder {
    return {
      ...item,
      productSummary: orderProductSummary(item),
      contractShipDateText: formatContractShipDate(item.contractShipDates),
      totalText: formatQuantity(item.totalQuantity),
      shippedText: formatQuantity(item.shippedQuantity),
      pendingText: formatQuantity(item.pendingQuantity),
      statusTone: statusTone(item.displayStatus),
    };
  },
  openDetail(event: WechatMiniprogram.TouchEvent) {
    const preview = this.data.previewMode ? "&preview=1" : "";
    wx.navigateTo({ url: `/pages/factory-task-detail/factory-task-detail?orderId=${encodeURIComponent(event.currentTarget.dataset.id)}${preview}` });
  },
  createShipment() {
    wx.navigateTo({ url: `/pages/factory-create-shipment/factory-create-shipment${this.data.previewMode ? "?preview=1" : ""}` });
  },
});
