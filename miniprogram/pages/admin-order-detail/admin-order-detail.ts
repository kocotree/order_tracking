import { orderApi, type Order } from "../../api/orders";
import { formatQuantity, orderProductSummary, statusTone } from "../../modules/orders/format";
import { isDevPreview, previewOrder } from "../../modules/dev-preview";

type FactoryProduct = {
  index: number;
  orderLineId: number;
  productName: string;
  propertiesValue: string;
  assignedText: string;
  shippedText: string;
};

type FactoryProgress = Order["factoryProgress"][number] & {
  orderText: string;
  shippedText: string;
  pendingText: string;
  products: FactoryProduct[];
};

Page({
  data: {
    order: null as Order | null,
    productSummary: "",
    statusTone: "pending",
    totalText: "0",
    shippedText: "0",
    factoryProgress: [] as FactoryProgress[],
    loading: true,
    error: "",
    expandedFactory: "",
  },
  onLoad(options: Record<string, string | undefined>) { if (isDevPreview(options)) { this.show(previewOrder()); return; } if (!options.orderId) { this.setData({ loading: false, error: "订单参数缺失" }); return; } void this.load(options.orderId); },
  show(order: Order) {
    const factoryProgress = order.factoryProgress.map((factory) => {
      const products = order.lines.flatMap((line) => line.assignments
        .filter((assignment) => assignment.factoryId === factory.factoryId)
        .map((assignment) => ({
          index: 0,
          orderLineId: line.orderLineId,
          productName: line.productName,
          propertiesValue: line.propertiesValue,
          assignedText: formatQuantity(assignment.assignedQuantity),
          shippedText: formatQuantity(assignment.shippedQuantity),
        })));
      return {
        ...factory,
        orderText: formatQuantity(factory.orderQuantity),
        shippedText: formatQuantity(factory.shippedQuantity),
        pendingText: formatQuantity(factory.pendingQuantity),
        products: products.map((product, index) => ({ ...product, index: index + 1 })),
      };
    });
    this.setData({
      order,
      productSummary: orderProductSummary(order),
      statusTone: statusTone(order.displayStatus),
      totalText: formatQuantity(order.totalQuantity),
      shippedText: formatQuantity(order.shippedQuantity),
      factoryProgress,
      loading: false,
    });
  },
  async load(orderId: string) { try { this.show(await orderApi.get(orderId)); } catch { this.setData({ error: "订单详情加载失败" }); } finally { this.setData({ loading: false }); } },
  goBack() { wx.navigateBack(); },
  toggleFactory(event: WechatMiniprogram.TouchEvent) {
    const id = String(event.currentTarget.dataset.id ?? "");
    this.setData({ expandedFactory: this.data.expandedFactory === id ? "" : id });
  },
});
