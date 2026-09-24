import { returnFromNotificationDetail } from "../../modules/navigation";
import { orderApi, type Order } from "../../api/orders";
import { formatContractShipDate, formatQuantity, orderProductSummary, statusTone } from "../../modules/orders/format";
import { isDevPreview, previewOrder } from "../../modules/dev-preview";
import { notificationApi } from "../../api/notifications";
import { notificationIdFrom } from "../../modules/notifications";

type FactoryProduct = {
  index: number;
  contractShipDateText: string;
  key: string;
  productName: string;
  propertiesValue: string;
  assignedText: string;
  shippedText: string;
};

type FactoryProgress = {
  factoryId: string;
  factoryName: string;
  progressPercent: number;
  contractShipDateText: string;
  showDetailContractDates: boolean;
  orderText: string;
  shippedText: string;
  pendingText: string;
  products: FactoryProduct[];
};

// 与后端 total() 一致：任一数量缺失则整组小计视为未知
function total(values: (number | null)[]): number | null {
  return values.some((value) => value == null) ? null : values.reduce<number>((sum, value) => sum + (value ?? 0), 0);
}

// 明细模式按明细上的工厂名分组，不区分派工状态；工厂名为空归入“—”
function detailProgress(details: Order["details"]): FactoryProgress[] {
  const groups = new Map<string, Order["details"]>();
  details.forEach((detail) => {
    const name = detail.factoryName || "—";
    groups.set(name, [...(groups.get(name) ?? []), detail]);
  });
  return Array.from(groups, ([factoryName, items]) => {
    const dates = items.map((item) => item.contractShipDate).filter((date): date is string => Boolean(date));
    const orderQuantity = total(items.map((item) => item.orderQuantity));
    const shippedQuantity = total(items.map((item) => item.shippedQuantity));
    return {
      factoryId: factoryName,
      factoryName,
      progressPercent: orderQuantity && shippedQuantity != null ? Math.round((shippedQuantity * 100) / orderQuantity) : 0,
      contractShipDateText: formatContractShipDate(dates),
      showDetailContractDates: new Set(dates).size > 1,
      orderText: formatQuantity(orderQuantity),
      shippedText: formatQuantity(shippedQuantity),
      pendingText: formatQuantity(total(items.map((item) => item.pendingQuantity))),
      products: items.map((item, index) => ({
        index: index + 1,
        key: item.detailId,
        contractShipDateText: formatContractShipDate(item.contractShipDate),
        productName: item.productName || "—",
        propertiesValue: item.propertiesValue || "—",
        assignedText: formatQuantity(item.orderQuantity),
        shippedText: formatQuantity(item.shippedQuantity),
      })),
    };
  });
}

Page({
  data: {
    order: null as Order | null,
    productSummary: "",
    contractShipDateText: "",
    statusTone: "pending",
    totalText: "0",
    shippedText: "0",
    factoryProgress: [] as FactoryProgress[],
    loading: true,
    error: "",
    expandedFactory: "",
    notificationId: null as number | null,
  },
  onLoad(options: Record<string, string | undefined>) { if (isDevPreview(options)) { this.show(previewOrder()); return; } if (!options.orderId) { this.setData({ loading: false, error: "订单参数缺失" }); return; } this.setData({ notificationId:notificationIdFrom(options) }); void this.load(options.orderId); },
  show(order: Order) {
    const factoryProgress = order.detailMode ? detailProgress(order.details) : order.factoryProgress.map((factory) => {
      const products = order.lines.flatMap((line) => line.assignments
        .filter((assignment) => assignment.factoryId === factory.factoryId)
        .map((assignment) => ({
          index: 0,
          contractShipDateText: formatContractShipDate(assignment.contractShipDate),
          key: String(line.orderLineId),
          productName: line.productName,
          propertiesValue: line.propertiesValue,
          assignedText: formatQuantity(assignment.assignedQuantity),
          shippedText: formatQuantity(assignment.shippedQuantity),
        })));
      const dates = products.map((product) => product.contractShipDateText).filter((date) => date !== "—");
      return {
        ...factory,
        contractShipDateText: formatContractShipDate(dates),
        showDetailContractDates: new Set(dates).size > 1,
        orderText: formatQuantity(factory.orderQuantity),
        shippedText: formatQuantity(factory.shippedQuantity),
        pendingText: formatQuantity(factory.pendingQuantity),
        products: products.map((product, index) => ({ ...product, index: index + 1 })),
      };
    });
    this.setData({
      order,
      contractShipDateText: formatContractShipDate(order.contractShipDates),
      productSummary: orderProductSummary(order),
      statusTone: statusTone(order.displayStatus),
      totalText: formatQuantity(order.totalQuantity),
      shippedText: formatQuantity(order.shippedQuantity),
      factoryProgress,
      loading: false,
    });
  },
  async load(orderId: string) { try { this.show(await orderApi.get(orderId)); if(this.data.notificationId)await notificationApi.markRead(this.data.notificationId); } catch { this.setData({ error: this.data.notificationId ? "内容已不可查看" : "订单详情加载失败" }); } finally { this.setData({ loading: false }); } },
  goBack() { returnFromNotificationDetail("order"); },
  toggleFactory(event: WechatMiniprogram.TouchEvent) {
    const id = String(event.currentTarget.dataset.id ?? "");
    this.setData({ expandedFactory: this.data.expandedFactory === id ? "" : id });
  },
});
