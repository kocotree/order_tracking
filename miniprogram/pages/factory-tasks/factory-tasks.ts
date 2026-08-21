import { orderApi, type Order } from "../../api/orders";
import { isDevPreview, previewOrder } from "../../modules/dev-preview";
import { clearSession, storedUser } from "../../modules/identity/session";
import { formatQuantity, orderProductSummary, statusTone } from "../../modules/orders/format";

type ViewOrder = Order & { productSummary: string; totalText: string; shippedText: string; pendingText: string; statusTone: string };

Page({
  data: { activeTab: "orders", items: [] as ViewOrder[], keyword: "", status: "all", filterOpen: false, loading: true, error: "", previewMode: false },
  onLoad(options: Record<string, string | undefined>) { const previewMode = isDevPreview(options); if (!previewMode && storedUser()?.role !== "factory") { clearSession(); wx.reLaunch({ url: "/pages/auth/auth" }); return; } this.setData({ previewMode }); if (previewMode) { this.setData({ loading: false, items: [this.toView(previewOrder(true))] }); return; } void this.loadOrders(); },
  onPullDownRefresh() { void this.loadOrders().finally(() => wx.stopPullDownRefresh()); },
  selectTab(event: WechatMiniprogram.TouchEvent) { this.setData({ activeTab: event.currentTarget.dataset.tab }); },
  keywordChanged(event: WechatMiniprogram.Input) { this.setData({ keyword: event.detail.value }); },
  search() { void this.loadOrders(); },
  toggleFilter() { this.setData({ filterOpen: !this.data.filterOpen }); },
  setStatus(event: WechatMiniprogram.TouchEvent) { this.setData({ status: event.currentTarget.dataset.status, filterOpen: false }); void this.loadOrders(); },
  async loadOrders() { this.setData({ loading: true, error: "" }); try { const result = await orderApi.list({ keyword: this.data.keyword, status: this.data.status }); this.setData({ items: result.items.map((item) => this.toView(item)) }); } catch { this.setData({ error: "任务加载失败，请下拉重试" }); } finally { this.setData({ loading: false }); } },
  toView(item: Order): ViewOrder { return { ...item, productSummary: orderProductSummary(item), totalText: formatQuantity(item.totalQuantity), shippedText: formatQuantity(item.shippedQuantity), pendingText: formatQuantity(item.pendingQuantity), statusTone: statusTone(item.displayStatus) }; },
  openDetail(event: WechatMiniprogram.TouchEvent) { const preview = this.data.previewMode ? "&preview=1" : ""; wx.navigateTo({ url: `/pages/factory-task-detail/factory-task-detail?orderId=${encodeURIComponent(event.currentTarget.dataset.id)}${preview}` }); },
  openProfile() { wx.reLaunch({ url: "/pages/profile/profile" }); },
});
