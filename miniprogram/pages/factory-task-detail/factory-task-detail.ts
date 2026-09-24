import { returnFromNotificationDetail } from "../../modules/navigation";
import { orderApi, type Order, type IncomingDifference } from "../../api/orders";
import { formatContractShipDate, formatQuantity, orderProductSummary, statusTone } from "../../modules/orders/format";
import { isDevPreview, previewOrder } from "../../modules/dev-preview";
import { notificationApi } from "../../api/notifications";
import { notificationIdFrom } from "../../modules/notifications";

type ViewLine = Order["lines"][number] & {
  index: number;
  contractShipDateText: string;
  orderText: string;
  shippedText: string;
  pendingText: string;
};

type ViewOrder = Order & {
  lines: ViewLine[];
};
type IncomingGroup = { productName: string; rows: { sequence: number; spec: string; quantityText: string; shortage: boolean }[] };

Page({
  data: {
    order: null as ViewOrder | null,
    productSummary: "",
    contractShipDateText: "",
    showDetailContractDates: false,
    statusTone: "pending",
    totalText: "0",
    shippedText: "0",
    pendingText: "0",
    loading: true,
    error: "",
    notificationId: null as number | null,
    incomingGroups: [] as IncomingGroup[],
    incomingExpanded: false,
  },
  onLoad(options: Record<string, string | undefined>) { if (isDevPreview(options)) { this.show(previewOrder(true)); return; } if (!options.orderId) { this.setData({ loading: false, error: "任务参数缺失" }); return; } this.setData({ notificationId:notificationIdFrom(options) }); void this.load(options.orderId); },
  show(order: Order) {
    const viewOrder: ViewOrder = {
      ...order,
      lines: order.lines.map((line, index) => ({
        ...line,
        index: index + 1,
        contractShipDateText: formatContractShipDate(line.assignments.map((item) => item.contractShipDate).filter((value): value is string => Boolean(value))),
        orderText: formatQuantity(line.orderQuantity),
        shippedText: formatQuantity(line.shippedQuantity),
        pendingText: formatQuantity(line.pendingQuantity),
      })),
    };
    this.setData({
      order: viewOrder,
      productSummary: orderProductSummary(order),
      contractShipDateText: formatContractShipDate(order.contractShipDates),
      showDetailContractDates: new Set(order.contractShipDates).size > 1,
      statusTone: statusTone(order.displayStatus),
      totalText: formatQuantity(order.totalQuantity),
      shippedText: formatQuantity(order.shippedQuantity),
      pendingText: formatQuantity(order.pendingQuantity),
      loading: false,
    });
  },
  showIncoming(records: IncomingDifference[]) {
    const groups = new Map<string, IncomingGroup>();
    for (const record of [...records].sort((a, b) => a.sequence - b.sequence)) {
      if (!groups.has(record.productName)) groups.set(record.productName, { productName: record.productName, rows: [] });
      groups.get(record.productName)!.rows.push({ sequence: record.sequence, spec: record.spec, quantityText: `${record.quantity < 0 ? "少" : "多"}${Math.abs(record.quantity).toLocaleString("zh-CN")}件`, shortage: record.quantity < 0 });
    }
    this.setData({ incomingGroups: [...groups.values()], incomingExpanded: false });
  },
  toggleIncoming() { this.setData({ incomingExpanded: !this.data.incomingExpanded }); },
  async load(orderId: string) { try { const [order, incoming] = await Promise.all([orderApi.get(orderId), orderApi.incomingDifferences(orderId)]); this.show(order); this.showIncoming(incoming.items); if(this.data.notificationId)await notificationApi.markRead(this.data.notificationId); } catch { this.setData({ error:this.data.notificationId?"内容已不可查看":"任务详情加载失败" }); } finally { this.setData({ loading: false }); } },
  goBack() { returnFromNotificationDetail("order"); },
});
