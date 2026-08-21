import type { Order } from "../../api/orders";

export function orderProductSummary(order: Order): string {
  return [...new Set(order.lines.map((item) => item.productName))].join("、") || "—";
}

export function orderPropertiesSummary(order: Order): string {
  return [...new Set(order.lines.map((item) => item.propertiesValue))].join("、") || "—";
}

export function formatQuantity(value: number): string {
  return value.toLocaleString("zh-CN");
}

export function statusTone(status: string): string {
  if (status === "已逾期") return "overdue";
  if (status === "已完成") return "completed";
  return "pending";
}
