import type { FactoryApplication, FactoryOption } from "../api/factory";
import type { Order } from "../api/orders";
import type { User } from "./identity/session";
import type { CatalogItem, Shipment } from "../api/shipments";

export type PreviewOptions = Record<string, string | undefined>;

export function canUseDevPreview(preview: string | undefined, platform: string): boolean {
  return preview === "1" && platform === "devtools";
}

export function isDevPreview(options: PreviewOptions): boolean {
  return canUseDevPreview(options.preview, wx.getDeviceInfo().platform);
}

export const PREVIEW_FACTORIES: FactoryOption[] = [
  { factoryId: "preview-factory-1", supplierNumber: "A01", factoryName: "禹帆" },
  { factoryId: "preview-factory-2", supplierNumber: "A10", factoryName: "温岭市新河禹帆制帽厂" },
];

export const PREVIEW_APPLICATION: FactoryApplication = {
  applicationId: "preview-application",
  userId: "preview-factory-user",
  realName: "王超",
  phoneMasked: "138****5122",
  position: "employee",
  requestedFactoryId: "preview-factory-1",
  requestedFactoryName: "禹帆",
  boundFactoryId: null,
  boundFactoryName: null,
  factoryContacts: [],
  status: "pending",
  rejectionReason: null,
  reviewedAt: null,
  reviewedBy: null,
  submittedAt: "2026-08-21 10:30",
  version: 1,
};

const PREVIEW_USER_BASE: User = {
  userId: "preview-user",
  role: "admin",
  isSuperAdmin: true,
  isEnabled: true,
  displayName: "演示最高管理员",
  feishuAvatarUrl: null,
  miniAvatarExternalUrl: null,
  miniAvatarFileId: null,
  phoneMasked: "138****5122",
  factoryId: null,
  factoryName: null,
  factoryPosition: null,
  version: 1,
  capabilities: [],
};

export function previewUser(variant: string | undefined): User {
  if (variant === "factory") {
    return {
      ...PREVIEW_USER_BASE,
      userId: "preview-factory-user",
      role: "factory",
      isSuperAdmin: false,
      displayName: "王超",
      factoryId: "preview-factory-1",
      factoryName: "禹帆",
      factoryPosition: "employee",
    };
  }
  return PREVIEW_USER_BASE;
}

export function previewOrder(factoryOnly = false): Order {
  const quantity = factoryOnly ? 40 : 100;
  const assignment = {
    assignmentId: 1, factoryId: "preview-factory-1", factoryName: "禹帆",
    assignedQuantity: quantity, shippedQuantity: 0, pendingQuantity: quantity,
    overQuantity: 0, shortQuantity: quantity, progressPercent: 0,
  };
  return {
    orderId: "preview-order", orderNo: "E81", source: "manual",
    orderDate: "2026-08-21", tracker: "松子", contractShipDate: "2026-08-30",
    lifecycle: "PUBLISHED", displayStatus: "未完成", version: 2,
    totalQuantity: quantity, shippedQuantity: 0, pendingQuantity: quantity,
    overQuantity: 0, shortQuantity: quantity, progressPercent: 0,
    lines: [{
      orderLineId: 1, variantId: "preview-variant", skuId: "SKU-E81-01",
      productName: "晴雨两用机能风衣", propertiesValue: "天蓝色 / 120",
      category: "童装", imageObjectKey: null, orderQuantity: quantity,
      shippedQuantity: 0, pendingQuantity: quantity, overQuantity: 0,
      shortQuantity: quantity, progressPercent: 0, assignments: [assignment],
    }],
    factoryProgress: [{
      factoryId: assignment.factoryId, factoryName: assignment.factoryName,
      orderQuantity: quantity, shippedQuantity: 0, pendingQuantity: quantity,
      overQuantity: 0, shortQuantity: quantity, progressPercent: 0,
    }],
    validationIssues: [], createdAt: "2026-08-21T08:00:00",
    updatedAt: "2026-08-21T09:00:00", requestId: "preview",
  };
}

export const PREVIEW_SHIPMENT_CATALOG: CatalogItem[] = [{ assignmentId:1, orderId:"preview-order", orderNo:"E81", contractShipDate:"2026-08-30", productName:"晴雨两用机能风衣", propertiesValue:"天蓝色 / 120", assignedQuantity:40, shippedQuantity:0, pendingQuantity:40 }];
export const PREVIEW_SHIPMENT: Shipment = { shipmentId:"preview-shipment", shipmentNo:"FH20260825-001", status:"SHIPPED", factoryId:"preview-factory-1", factoryName:"禹帆", createdBy:"preview-factory-user", preferredOrderId:"preview-order", businessDate:"2026-08-25", note:"物流车辆浙A·K2688", totalBoxes:3, totalQuantity:40, createdAt:"2026-08-25T09:20:00+08:00", submittedAt:"2026-08-25T10:00:00+08:00", lines:[{assignmentId:1,orderId:"preview-order",orderNo:"E81",skuId:"SKU-E81-01",productName:"晴雨两用机能风衣",propertiesValue:"天蓝色 / 120",quantity:40}], boxes:[{boxNo:1,groupKey:"group-a",items:[{assignmentId:1,orderId:"preview-order",orderNo:"E81",skuId:"SKU-E81-01",productName:"晴雨两用机能风衣",propertiesValue:"天蓝色 / 120",quantity:15}]},{boxNo:2,groupKey:"group-a",items:[{assignmentId:1,orderId:"preview-order",orderNo:"E81",skuId:"SKU-E81-01",productName:"晴雨两用机能风衣",propertiesValue:"天蓝色 / 120",quantity:15}]},{boxNo:3,groupKey:null,items:[{assignmentId:1,orderId:"preview-order",orderNo:"E81",skuId:"SKU-E81-01",productName:"晴雨两用机能风衣",propertiesValue:"天蓝色 / 120",quantity:10}]}] };

export const PREVIEW_FACTORY_SHIPMENTS: Shipment[] = [
  {
    ...PREVIEW_SHIPMENT,
    shipmentId: "preview-shipment-1",
    shipmentNo: "FH20260818-003",
    businessDate: "2026-08-18",
    totalQuantity: 400,
    lines: [
      { ...PREVIEW_SHIPMENT.lines[0], orderNo: "E81#", productName: "乐园游会吊带包屁衣", propertiesValue: "蓝色 / 90", quantity: 100 },
      { ...PREVIEW_SHIPMENT.lines[0], assignmentId: 2, orderNo: "E81#", productName: "乐园游会吊带包屁衣", propertiesValue: "蓝色 / 100", quantity: 300 },
    ],
  },
  {
    ...PREVIEW_SHIPMENT,
    shipmentId: "preview-shipment-2",
    shipmentNo: "FH20260816-002",
    businessDate: "2026-08-16",
    totalBoxes: 4,
    totalQuantity: 600,
    lines: [
      { ...PREVIEW_SHIPMENT.lines[0], orderNo: "E92#", productName: "小热皮绒绒裤", propertiesValue: "棕色 / 100", quantity: 400 },
      { ...PREVIEW_SHIPMENT.lines[0], assignmentId: 2, orderId: "preview-order-2", orderNo: "E35#", productName: "轻量防风马甲", propertiesValue: "橙色 / 110", quantity: 200 },
    ],
  },
  {
    ...PREVIEW_SHIPMENT,
    shipmentId: "preview-shipment-3",
    shipmentNo: "FH20260810-001",
    businessDate: "2026-08-10",
    totalBoxes: 2,
    totalQuantity: 900,
    lines: [
      { ...PREVIEW_SHIPMENT.lines[0], orderNo: "E78#", productName: "秋日摇粒绒外套", propertiesValue: "雾蓝 / 120", quantity: 450 },
      { ...PREVIEW_SHIPMENT.lines[0], assignmentId: 2, orderNo: "E78#", productName: "秋日摇粒绒外套", propertiesValue: "雾蓝 / 130", quantity: 450 },
    ],
  },
];
