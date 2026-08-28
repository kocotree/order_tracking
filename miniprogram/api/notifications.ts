import type { components } from "./generated";
import { SUBSCRIPTION_TEMPLATE_IDS } from "./config";
import { authorizedRequest } from "./identity";
import { buildSubscriptionRequest, mapSubscriptionResults, type MiniRole } from "../modules/notifications";

export type NotificationItem = components["schemas"]["NotificationResponse"];
export type NotificationList = components["schemas"]["NotificationListResponse"];
type UnreadCount = components["schemas"]["UnreadCountResponse"];

export const notificationApi = {
  list: (status:"all"|"unread"="all", page=1, pageSize=10) => authorizedRequest<NotificationList>({ url:`/mini/notifications?status=${status}&page=${page}&pageSize=${pageSize}`, method:"GET" }),
  unreadCount: () => authorizedRequest<UnreadCount>({ url:"/mini/notifications/unread-count", method:"GET" }),
  markRead: (notificationId:number) => authorizedRequest<WechatMiniprogram.IAnyObject>({ url:`/mini/notifications/${notificationId}/read`, method:"POST" }),
  recordAuthorizations: (results:Record<string,"accepted"|"rejected"|"closed">) => authorizedRequest<WechatMiniprogram.IAnyObject>({ url:"/mini/notification-authorizations", method:"POST", data:{ results } }),
};

export async function requestNotificationSubscriptions(role:MiniRole):Promise<"accepted"|"declined"|"unavailable"> {
  const mapping = SUBSCRIPTION_TEMPLATE_IDS;
  const { templateIds, missingKeys } = buildSubscriptionRequest(role, mapping);
  if (!templateIds.length || missingKeys.length) return "unavailable";
  const raw = await new Promise<Record<string,string>>((resolve, reject) => wx.requestSubscribeMessage({ tmplIds:templateIds, success:resolve as never, fail:reject }));
  const results = mapSubscriptionResults(role, mapping, raw);
  if (Object.keys(results).length) await notificationApi.recordAuthorizations(results);
  return Object.values(results).includes("accepted") ? "accepted" : "declined";
}
