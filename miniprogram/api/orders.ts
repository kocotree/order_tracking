import type { components } from "./generated";
import { authorizedRequest } from "./identity";

export type Order = components["schemas"]["OrderResponse"];
export type OrderList = components["schemas"]["OrderListResponse"];

export const orderApi = {
  list: (params: {
    keyword?: string;
    status?: string;
    factoryId?: string;
    trackers?: string[];
    shipDateFrom?: string;
    shipDateTo?: string;
    sortBy?: string;
    page?: number;
    pageSize?: number;
  } = {}) => {
    const values = [
      ["keyword", params.keyword ?? ""],
      ["status", params.status ?? "all"],
      ["sortBy", params.sortBy ?? "priority"],
      ["page", String(params.page ?? 1)],
      ["pageSize", String(params.pageSize ?? 20)],
    ];
    if (params.factoryId) values.push(["factoryId", params.factoryId]);
    if (params.trackers) {
      values.push(...params.trackers.map((tracker) => ["trackers", tracker]));
    }
    if (params.shipDateFrom) values.push(["shipDateFrom", params.shipDateFrom]);
    if (params.shipDateTo) values.push(["shipDateTo", params.shipDateTo]);
    const query = values
      .map(([key, value]) => `${key}=${encodeURIComponent(value)}`)
      .join("&");
    return authorizedRequest<OrderList>({ url: `/orders?${query}`, method: "GET" });
  },
  get: (orderId: string) =>
    authorizedRequest<Order>({
      url: `/orders/${encodeURIComponent(orderId)}`,
      method: "GET",
    }),
};
