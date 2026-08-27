import { orderApi, type Order } from "../../api/orders";
import { factoryApi } from "../../api/factory";
import { isDevPreview, PREVIEW_FACTORIES, previewOrder } from "../../modules/dev-preview";
import { clearSession, storedUser } from "../../modules/identity/session";
import { adminNavigationItems } from "../../modules/navigation";
import {
  formatContractShipDate,
  formatQuantity,
  orderFactorySummary,
  orderProductSummary,
  statusTone,
} from "../../modules/orders/format";

type ViewOrder = Order & {
  productSummary: string;
  factorySummary: string;
  contractShipDateText: string;
  totalText: string;
  shippedText: string;
  pendingText: string;
  statusTone: string;
};

type FilterOption = { label: string; value: string };

const STATUS_OPTIONS: FilterOption[] = [
  { label: "全部状态", value: "all" },
  { label: "未完成", value: "未完成" },
  { label: "已逾期", value: "已逾期" },
  { label: "已完成", value: "已完成" },
];
const TRACKER_OPTIONS: FilterOption[] = [
  { label: "全部跟单人员", value: "" },
  ...["烧麦", "松子", "橄榄", "大葱", "青椒"].map((value) => ({ label: value, value })),
];
const SORT_OPTIONS: FilterOption[] = [
  { label: "默认紧急程度", value: "priority" },
  { label: "合同出货时间升序", value: "shipDateAsc" },
  { label: "合同出货时间降序", value: "shipDateDesc" },
  { label: "订单日期最新", value: "orderDateDesc" },
  { label: "更新时间最新", value: "updatedDesc" },
];

function optionIndex(options: FilterOption[], value: string): number {
  const index = options.findIndex((item) => item.value === value);
  return index < 0 ? 0 : index;
}

function activeFilterCount(values: {
  status: string;
  factoryId: string;
  tracker: string;
  shipDateFrom: string;
  shipDateTo: string;
  sortBy: string;
}): number {
  return [
    values.status !== "all",
    Boolean(values.factoryId),
    Boolean(values.tracker),
    Boolean(values.shipDateFrom),
    Boolean(values.shipDateTo),
    values.sortBy !== "priority",
  ].filter(Boolean).length;
}

Page({
  data: {
    items: [] as ViewOrder[],
    keyword: "",
    status: "all",
    factoryId: "",
    tracker: "",
    shipDateFrom: "",
    shipDateTo: "",
    sortBy: "priority",
    activeFilterCount: 0,
    statusOptions: STATUS_OPTIONS,
    factoryOptions: [{ label: "全部工厂", value: "" }] as FilterOption[],
    trackerOptions: TRACKER_OPTIONS,
    sortOptions: SORT_OPTIONS,
    draftStatusIndex: 0,
    draftFactoryIndex: 0,
    draftTrackerIndex: 0,
    draftSortIndex: 0,
    draftShipDateFrom: "",
    draftShipDateTo: "",
    filterOpen: false,
    loading: true,
    error: "",
    previewMode: false,
    navigationItems: adminNavigationItems(),
  },
  onLoad(options: Record<string, string | undefined>) {
    const previewMode = isDevPreview(options);
    if (!previewMode && storedUser()?.role !== "admin") { clearSession(); wx.reLaunch({ url: "/pages/auth/auth" }); return; }
    this.setData({ previewMode });
    if (previewMode) {
      this.setData({
        loading: false,
        items: [this.toView(previewOrder())],
        factoryOptions: [
          { label: "全部工厂", value: "" },
          ...PREVIEW_FACTORIES.map((factory) => ({ label: factory.factoryName, value: factory.factoryId })),
        ],
      });
      return;
    }
    void this.loadFilterOptions();
    void this.loadOrders();
  },
  onPullDownRefresh() { void this.loadOrders().finally(() => wx.stopPullDownRefresh()); },
  keywordChanged(event: WechatMiniprogram.Input) { this.setData({ keyword: event.detail.value }); },
  search() { void this.loadOrders(); },
  toggleFilter() {
    if (this.data.filterOpen) { this.closeFilter(); return; }
    this.setData({
      filterOpen: true,
      draftStatusIndex: optionIndex(this.data.statusOptions, this.data.status),
      draftFactoryIndex: optionIndex(this.data.factoryOptions, this.data.factoryId),
      draftTrackerIndex: optionIndex(this.data.trackerOptions, this.data.tracker),
      draftSortIndex: optionIndex(this.data.sortOptions, this.data.sortBy),
      draftShipDateFrom: this.data.shipDateFrom,
      draftShipDateTo: this.data.shipDateTo,
    });
  },
  closeFilter() { this.setData({ filterOpen: false }); },
  stopPropagation() {},
  statusChanged(event: WechatMiniprogram.PickerChange) { this.setData({ draftStatusIndex: Number(event.detail.value) }); },
  factoryChanged(event: WechatMiniprogram.PickerChange) { this.setData({ draftFactoryIndex: Number(event.detail.value) }); },
  trackerChanged(event: WechatMiniprogram.PickerChange) { this.setData({ draftTrackerIndex: Number(event.detail.value) }); },
  sortChanged(event: WechatMiniprogram.PickerChange) { this.setData({ draftSortIndex: Number(event.detail.value) }); },
  shipDateFromChanged(event: WechatMiniprogram.PickerChange) { this.setData({ draftShipDateFrom: String(event.detail.value) }); },
  shipDateToChanged(event: WechatMiniprogram.PickerChange) { this.setData({ draftShipDateTo: String(event.detail.value) }); },
  resetFilter() {
    this.setData({
      draftStatusIndex: 0,
      draftFactoryIndex: 0,
      draftTrackerIndex: 0,
      draftSortIndex: 0,
      draftShipDateFrom: "",
      draftShipDateTo: "",
    });
  },
  applyFilter() {
    if (this.data.draftShipDateFrom && this.data.draftShipDateTo && this.data.draftShipDateFrom > this.data.draftShipDateTo) {
      wx.showToast({ title: "开始日期不能晚于结束日期", icon: "none" });
      return;
    }
    const values = {
      status: this.data.statusOptions[this.data.draftStatusIndex]?.value ?? "all",
      factoryId: this.data.factoryOptions[this.data.draftFactoryIndex]?.value ?? "",
      tracker: this.data.trackerOptions[this.data.draftTrackerIndex]?.value ?? "",
      shipDateFrom: this.data.draftShipDateFrom,
      shipDateTo: this.data.draftShipDateTo,
      sortBy: this.data.sortOptions[this.data.draftSortIndex]?.value ?? "priority",
    };
    this.setData({ ...values, activeFilterCount: activeFilterCount(values), filterOpen: false }, () => { void this.loadOrders(); });
  },
  async loadFilterOptions() {
    try {
      const result = await factoryApi.listFactories();
      this.setData({
        factoryOptions: [
          { label: "全部工厂", value: "" },
          ...result.items.map((factory) => ({ label: factory.factoryName, value: factory.factoryId })),
        ],
      });
    } catch {
      wx.showToast({ title: "工厂筛选项加载失败", icon: "none" });
    }
  },
  async loadOrders() {
    this.setData({ loading: true, error: "" });
    try {
      if (this.data.previewMode) {
        const order = previewOrder();
        const keyword = this.data.keyword.trim().toLowerCase();
        const matches = (!keyword || order.orderNo.toLowerCase().includes(keyword) || order.lines.some((line) => line.productName.toLowerCase().includes(keyword)))
          && (this.data.status === "all" || order.displayStatus === this.data.status)
          && (!this.data.factoryId || order.factoryProgress.some((factory) => factory.factoryId === this.data.factoryId))
          && (!this.data.tracker || order.tracker === this.data.tracker)
          && (!this.data.shipDateFrom || order.contractShipDate >= this.data.shipDateFrom)
          && (!this.data.shipDateTo || order.contractShipDate <= this.data.shipDateTo);
        this.setData({ items: matches ? [this.toView(order)] : [] });
        return;
      }
      const result = await orderApi.list({
        keyword: this.data.keyword,
        status: this.data.status,
        factoryId: this.data.factoryId || undefined,
        trackers: this.data.tracker ? [this.data.tracker] : undefined,
        shipDateFrom: this.data.shipDateFrom || undefined,
        shipDateTo: this.data.shipDateTo || undefined,
        sortBy: this.data.sortBy,
      });
      this.setData({ items: result.items.map((item) => this.toView(item)) });
    } catch { this.setData({ error: "订单加载失败，请下拉重试" }); }
    finally { this.setData({ loading: false }); }
  },
  toView(item: Order): ViewOrder {
    return {
      ...item,
      productSummary: orderProductSummary(item),
      factorySummary: orderFactorySummary(item),
      contractShipDateText: formatContractShipDate(item.contractShipDate),
      totalText: formatQuantity(item.totalQuantity),
      shippedText: formatQuantity(item.shippedQuantity),
      pendingText: formatQuantity(item.pendingQuantity),
      statusTone: statusTone(item.displayStatus),
    };
  },
  openDetail(event: WechatMiniprogram.TouchEvent) { const preview = this.data.previewMode ? "&preview=1" : ""; wx.navigateTo({ url: `/pages/admin-order-detail/admin-order-detail?orderId=${encodeURIComponent(event.currentTarget.dataset.id)}${preview}` }); },
});
