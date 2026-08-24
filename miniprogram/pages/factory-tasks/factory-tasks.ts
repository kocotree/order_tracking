import { orderApi, type Order } from "../../api/orders";
import { isDevPreview, previewOrder } from "../../modules/dev-preview";
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

const statusOptions: FilterOption[] = [
  { label: "全部状态", value: "all" },
  { label: "未完成", value: "未完成" },
  { label: "已逾期", value: "已逾期" },
  { label: "已完成", value: "已完成" },
];

function optionIndex(options: FilterOption[], value: string): number {
  const index = options.findIndex((option) => option.value === value);
  return index < 0 ? 0 : index;
}

function countFilters(values: { status: string; shipDateFrom: string; shipDateTo: string }): number {
  return [values.status !== "all", Boolean(values.shipDateFrom), Boolean(values.shipDateTo)].filter(Boolean).length;
}

Page({
  data: {
    activeTab: "orders",
    items: [] as ViewOrder[],
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
    loading: true,
    error: "",
    previewMode: false,
  },
  onLoad(options: Record<string, string | undefined>) {
    const previewMode = isDevPreview(options);
    if (!previewMode && storedUser()?.role !== "factory") {
      clearSession();
      wx.reLaunch({ url: "/pages/auth/auth" });
      return;
    }
    this.setData({ previewMode });
    void this.loadOrders();
  },
  onPullDownRefresh() { void this.loadOrders().finally(() => wx.stopPullDownRefresh()); },
  selectTab(event: WechatMiniprogram.TouchEvent) { this.setData({ activeTab: event.currentTarget.dataset.tab, filterOpen: false }); },
  keywordChanged(event: WechatMiniprogram.Input) { this.setData({ keyword: event.detail.value }); },
  search() { void this.loadOrders(); },
  toggleFilter() {
    if (this.data.filterOpen) { this.closeFilter(); return; }
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
  resetFilter() { this.setData({ draftStatusIndex: 0, draftShipDateFrom: "", draftShipDateTo: "" }); },
  applyFilter() {
    if (this.data.draftShipDateFrom && this.data.draftShipDateTo && this.data.draftShipDateFrom > this.data.draftShipDateTo) {
      wx.showToast({ title: "开始日期不能晚于结束日期", icon: "none" });
      return;
    }
    const values = {
      status: this.data.statusOptions[this.data.draftStatusIndex]?.value ?? "all",
      shipDateFrom: this.data.draftShipDateFrom,
      shipDateTo: this.data.draftShipDateTo,
    };
    this.setData({ ...values, activeFilterCount: countFilters(values), filterOpen: false }, () => { void this.loadOrders(); });
  },
  async loadOrders() {
    this.setData({ loading: true, error: "" });
    try {
      if (this.data.previewMode) {
        const order = previewOrder(true);
        const keyword = this.data.keyword.trim().toLowerCase();
        const matches = (!keyword || order.orderNo.toLowerCase().includes(keyword) || order.lines.some((line) => line.productName.toLowerCase().includes(keyword)))
          && (this.data.status === "all" || order.displayStatus === this.data.status)
          && (!this.data.shipDateFrom || order.contractShipDate >= this.data.shipDateFrom)
          && (!this.data.shipDateTo || order.contractShipDate <= this.data.shipDateTo);
        this.setData({ items: matches ? [this.toView(order)] : [] });
        return;
      }
      const result = await orderApi.list({
        keyword: this.data.keyword,
        status: this.data.status,
        shipDateFrom: this.data.shipDateFrom || undefined,
        shipDateTo: this.data.shipDateTo || undefined,
      });
      this.setData({ items: result.items.map((item) => this.toView(item)) });
    } catch { this.setData({ error: "任务加载失败，请下拉重试" }); }
    finally { this.setData({ loading: false }); }
  },
  toView(item: Order): ViewOrder {
    return {
      ...item,
      productSummary: orderProductSummary(item),
      contractShipDateText: formatContractShipDate(item.contractShipDate),
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
  openProfile() { wx.reLaunch({ url: "/pages/profile/profile" }); },
});
