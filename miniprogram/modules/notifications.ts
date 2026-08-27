export type MiniRole = "admin" | "factory";
export type AuthorizationResult = "accepted" | "rejected" | "closed";
export type TemplateMapping = Partial<Record<string, string>>;

const ROLE_KEYS: Record<MiniRole, readonly string[]> = {
  admin: ["admin_shipment", "admin_repair"],
  factory: ["factory_order", "factory_repair"],
};

const APPROVED_TARGETS = [
  "/pages/admin-order-detail/admin-order-detail",
  "/pages/admin-shipment-detail/admin-shipment-detail",
  "/pages/admin-repair-detail/admin-repair-detail",
  "/pages/factory-task-detail/factory-task-detail",
  "/pages/factory-shipment-detail/factory-shipment-detail",
  "/pages/factory-repair-detail/factory-repair-detail",
  "/pages/admin-orders/admin-orders",
  "/pages/factory-tasks/factory-tasks",
];

export function buildSubscriptionRequest(role: MiniRole, mapping: TemplateMapping): { templateIds:string[]; missingKeys:string[] } {
  const keys = ROLE_KEYS[role];
  const missingKeys = keys.filter((key) => !mapping[key]?.trim());
  const templateIds = [...new Set(keys.map((key) => mapping[key]?.trim()).filter((value): value is string => Boolean(value)))];
  if (templateIds.length > 3) throw new Error("微信单次订阅模板不能超过 3 个");
  return { templateIds, missingKeys };
}

export function mapSubscriptionResults(role:MiniRole, mapping:TemplateMapping, raw:Record<string,string>):Record<string,AuthorizationResult> {
  const result:Record<string,AuthorizationResult> = {};
  for (const key of ROLE_KEYS[role]) {
    const templateId = mapping[key];
    if (!templateId) continue;
    const value = raw[templateId];
    result[key] = value === "accept" ? "accepted" : value === "reject" ? "rejected" : "closed";
  }
  return result;
}

export function notificationTarget(targetPath:string, targetType:string, targetId:string, notificationId:number, status:"all"|"unread"):string|null {
  let page = targetPath;
  if (!APPROVED_TARGETS.some((path) => page.startsWith(path))) {
    page = targetType === "order" ? `/pages/admin-order-detail/admin-order-detail?orderId=${encodeURIComponent(targetId)}`
      : targetType === "shipment" ? `/pages/admin-shipment-detail/admin-shipment-detail?shipmentId=${encodeURIComponent(targetId)}`
      : targetType === "repair" ? `/pages/admin-repair-detail/admin-repair-detail?repairId=${encodeURIComponent(targetId)}`
      : targetType === "factory_task" ? `/pages/factory-task-detail/factory-task-detail?orderId=${encodeURIComponent(targetId)}`
      : targetType === "factory_task_list" ? "/pages/factory-tasks/factory-tasks" : "";
  }
  if (!page) return null;
  const separator = page.includes("?") ? "&" : "?";
  return `${page}${separator}notificationId=${notificationId}&notificationStatus=${status}`;
}

export function notificationIdFrom(options:Record<string,string|undefined>):number|null {
  const value = Number(options.notificationId);
  return Number.isInteger(value) && value > 0 ? value : null;
}
