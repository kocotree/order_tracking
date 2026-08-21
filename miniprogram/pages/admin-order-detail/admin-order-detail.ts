import { orderApi, type Order } from "../../api/orders";
import { formatQuantity, orderProductSummary, statusTone } from "../../modules/orders/format";
import { isDevPreview, previewOrder } from "../../modules/dev-preview";

Page({
  data: { order: null as Order | null, productSummary: "", statusTone: "pending", totalText: "0", shippedText: "0", pendingText: "0", loading: true, error: "", expandedFactory: "" },
  onLoad(options: Record<string, string | undefined>) { if (isDevPreview(options)) { this.show(previewOrder()); return; } if (!options.orderId) { this.setData({ loading: false, error: "订单参数缺失" }); return; } void this.load(options.orderId); },
  show(order: Order) { this.setData({ order, productSummary: orderProductSummary(order), statusTone: statusTone(order.displayStatus), totalText: formatQuantity(order.totalQuantity), shippedText: formatQuantity(order.shippedQuantity), pendingText: formatQuantity(order.pendingQuantity), loading: false }); },
  async load(orderId: string) { try { this.show(await orderApi.get(orderId)); } catch { this.setData({ error: "订单详情加载失败" }); } finally { this.setData({ loading: false }); } },
  toggleFactory(event: WechatMiniprogram.TouchEvent) { const id = event.currentTarget.dataset.id; this.setData({ expandedFactory: this.data.expandedFactory === id ? "" : id }); },
});
