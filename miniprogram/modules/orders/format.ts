import type { Order } from "../../api/orders";

export function orderProductSummary(order: Order): string {
  return [...new Set(order.lines.map((item) => item.productName))].join("、") || "—";
}

export function orderPropertiesSummary(order: Order): string {
  return [...new Set(order.lines.map((item) => item.propertiesValue))].join("、") || "—";
}

export function orderFactorySummary(order: Order): string {
  return [...new Set(order.factoryProgress.map((item) => item.factoryName))].join("、") || "—";
}

export function formatContractShipDate(value: string, today = new Date()): string {
  const todayValue = [
    today.getFullYear(),
    String(today.getMonth() + 1).padStart(2, "0"),
    String(today.getDate()).padStart(2, "0"),
  ].join("-");
  if (value === todayValue) return "今天";
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  return match ? `${match[2]}月${match[3]}日` : value;
}

export function formatQuantity(value: number): string {
  return value.toLocaleString("zh-CN");
}

export function statusTone(status: string): string {
  if (status === "已逾期") return "overdue";
  if (status === "已完成") return "completed";
  return "pending";
}
