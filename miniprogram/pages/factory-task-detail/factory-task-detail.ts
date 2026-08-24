import { orderApi, type Order } from "../../api/orders";
import { formatContractShipDate, formatQuantity, orderProductSummary, statusTone } from "../../modules/orders/format";
import { isDevPreview, previewOrder } from "../../modules/dev-preview";

type ViewLine = Order["lines"][number] & {
  index: number;
  orderText: string;
  shippedText: string;
  pendingText: string;
};

type ViewOrder = Order & {
  lines: ViewLine[];
};

Page({
  data: {
    order: null as ViewOrder | null,
    productSummary: "",
    contractShipDateText: "",
    statusTone: "pending",
    totalText: "0",
    shippedText: "0",
    pendingText: "0",
    loading: true,
    error: "",
  },
  onLoad(options: Record<string, string | undefined>) { if (isDevPreview(options)) { this.show(previewOrder(true)); return; } if (!options.orderId) { this.setData({ loading: false, error: "任务参数缺失" }); return; } void this.load(options.orderId); },
  show(order: Order) {
    const viewOrder: ViewOrder = {
      ...order,
      lines: order.lines.map((line, index) => ({
        ...line,
        index: index + 1,
        orderText: formatQuantity(line.orderQuantity),
        shippedText: formatQuantity(line.shippedQuantity),
        pendingText: formatQuantity(line.pendingQuantity),
      })),
    };
    this.setData({
      order: viewOrder,
      productSummary: orderProductSummary(order),
      contractShipDateText: formatContractShipDate(order.contractShipDate),
      statusTone: statusTone(order.displayStatus),
      totalText: formatQuantity(order.totalQuantity),
      shippedText: formatQuantity(order.shippedQuantity),
      pendingText: formatQuantity(order.pendingQuantity),
      loading: false,
    });
  },
  async load(orderId: string) { try { this.show(await orderApi.get(orderId)); } catch { this.setData({ error: "任务详情加载失败" }); } finally { this.setData({ loading: false }); } },
  goBack() { wx.navigateBack(); },
});
