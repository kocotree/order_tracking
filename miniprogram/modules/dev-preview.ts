import type { FactoryApplication, FactoryOption } from "../api/factory";
import type { Order } from "../api/orders";
import type { User } from "./identity/session";
import type { CatalogItem, Shipment } from "../api/shipments";
import type { Repair } from "../api/repairs";

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
export const PREVIEW_SHIPMENT: Shipment = { shipmentId:"preview-shipment", shipmentNo:"FH20260825-001", status:"SHIPPED", factoryId:"preview-factory-1", factoryName:"禹帆", createdBy:"preview-factory-user", preferredOrderId:"preview-order", businessDate:"2026-08-25", note:"物流车辆浙A·K2688", totalBoxes:3, totalQuantity:40, createdAt:"2026-08-25T09:20:00+08:00", submittedAt:"2026-08-25T10:00:00+08:00", files:[], lines:[{assignmentId:1,orderId:"preview-order",orderNo:"E81",skuId:"SKU-E81-01",productName:"晴雨两用机能风衣",propertiesValue:"天蓝色 / 120",quantity:40}], boxes:[{boxNo:1,groupKey:"group-a",items:[{assignmentId:1,orderId:"preview-order",orderNo:"E81",skuId:"SKU-E81-01",productName:"晴雨两用机能风衣",propertiesValue:"天蓝色 / 120",quantity:15}]},{boxNo:2,groupKey:"group-a",items:[{assignmentId:1,orderId:"preview-order",orderNo:"E81",skuId:"SKU-E81-01",productName:"晴雨两用机能风衣",propertiesValue:"天蓝色 / 120",quantity:15}]},{boxNo:3,groupKey:null,items:[{assignmentId:1,orderId:"preview-order",orderNo:"E81",skuId:"SKU-E81-01",productName:"晴雨两用机能风衣",propertiesValue:"天蓝色 / 120",quantity:10}]}] };

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

export const PREVIEW_REPAIRS: Repair[] = [
  {
    repairId: "preview-repair-1",
    repairNo: "FX20260812-001",
    status: "INCOMPLETE",
    returnDate: "2026-08-12",
    factoryId: "preview-factory-1",
    factoryName: "禹帆",
    warehouseReturnQuantity: 400,
    repairedQuantity: 0,
    scrappedQuantity: 0,
    returnedQuantity: 0,
    originalFileId: 900001,
    originalFilename: "质检单_20260812.xlsx",
    originalSizeBytes: 292864,
    createdAt: "2026-08-12T09:30:00+08:00",
    lines: [
      { inspectionLineId: 900001, sourceRow: 2, sourceOrder: 1, boxNumber: "1", sourceSkuId: "PREVIEW-001", productName: "云朵软壳冲锋衣", propertiesValue: "松石绿/110", warehouseReturnQuantity: 160, reason: "车线不齐" },
      { inspectionLineId: 900002, sourceRow: 3, sourceOrder: 2, boxNumber: "1", sourceSkuId: "PREVIEW-002", productName: "云朵软壳冲锋衣", propertiesValue: "米白/110", warehouseReturnQuantity: 120, reason: "轻微污渍" },
      { inspectionLineId: 900003, sourceRow: 4, sourceOrder: 3, boxNumber: "2", sourceSkuId: "PREVIEW-003", productName: "小热皮绒绒裤", propertiesValue: "棕色/100", warehouseReturnQuantity: 120, reason: "尺寸偏差" },
    ],
    specs: [
      { variantId:"preview-variant-1",sourceSkuId:"PREVIEW-001",sourceProductId:"PREVIEW-P1",productName:"云朵软壳冲锋衣",propertiesValue:"松石绿/110",warehouseReturnQuantity:160,repairedQuantity:0,scrappedQuantity:0,returnedQuantity:0,pendingQuantity:160 },
      { variantId:"preview-variant-2",sourceSkuId:"PREVIEW-002",sourceProductId:"PREVIEW-P1",productName:"云朵软壳冲锋衣",propertiesValue:"米白/110",warehouseReturnQuantity:120,repairedQuantity:0,scrappedQuantity:0,returnedQuantity:0,pendingQuantity:120 },
      { variantId:"preview-variant-3",sourceSkuId:"PREVIEW-003",sourceProductId:"PREVIEW-P2",productName:"小热皮绒绒裤",propertiesValue:"棕色/100",warehouseReturnQuantity:120,repairedQuantity:0,scrappedQuantity:0,returnedQuantity:0,pendingQuantity:120 },
    ],
    returnBatches: [],
  },
  {
    repairId: "preview-repair-2",
    repairNo: "FX20260810-002",
    status: "INCOMPLETE",
    returnDate: "2026-08-10",
    factoryId: "preview-factory-1",
    factoryName: "禹帆",
    warehouseReturnQuantity: 900,
    repairedQuantity: 330,
    scrappedQuantity: 90,
    returnedQuantity: 420,
    originalFileId: 900002,
    originalFilename: "质检单_20260810.xlsx",
    originalSizeBytes: 321536,
    createdAt: "2026-08-10T10:18:00+08:00",
    lines: [
      { inspectionLineId: 900004, sourceRow: 2, sourceOrder: 1, boxNumber: "1", sourceSkuId: "PREVIEW-004", productName: "乐园游会吊带包屁衣", propertiesValue: "蓝色/90", warehouseReturnQuantity: 450, reason: "面料破损" },
      { inspectionLineId: 900005, sourceRow: 3, sourceOrder: 2, boxNumber: "2", sourceSkuId: "PREVIEW-005", productName: "乐园游会吊带包屁衣", propertiesValue: "蓝色/100", warehouseReturnQuantity: 450, reason: "印花偏位" },
    ],
    specs: [
      { variantId:"preview-variant-4",sourceSkuId:"PREVIEW-004",sourceProductId:"PREVIEW-P3",productName:"乐园游会吊带包屁衣",propertiesValue:"蓝色/90",warehouseReturnQuantity:450,repairedQuantity:180,scrappedQuantity:40,returnedQuantity:220,pendingQuantity:230 },
      { variantId:"preview-variant-5",sourceSkuId:"PREVIEW-005",sourceProductId:"PREVIEW-P3",productName:"乐园游会吊带包屁衣",propertiesValue:"蓝色/100",warehouseReturnQuantity:450,repairedQuantity:150,scrappedQuantity:50,returnedQuantity:200,pendingQuantity:250 },
    ],
    returnBatches: [{
      batchId:"preview-batch-1",submittedAt:"2026-08-20T10:00:00+08:00",returnDate:"2026-08-20",submittedBy:"preview-factory-user",
      lines:[
        { variantId:"preview-variant-4",sourceSkuId:"PREVIEW-004",sourceProductId:"PREVIEW-P3",productName:"乐园游会吊带包屁衣",propertiesValue:"蓝色/90",warehouseReturnQuantity:450,repairedQuantity:180,scrappedQuantity:40 },
        { variantId:"preview-variant-5",sourceSkuId:"PREVIEW-005",sourceProductId:"PREVIEW-P3",productName:"乐园游会吊带包屁衣",propertiesValue:"蓝色/100",warehouseReturnQuantity:450,repairedQuantity:150,scrappedQuantity:50 },
      ].map(line=>({...line,returnedQuantity:line.repairedQuantity+line.scrappedQuantity})),
    }],
  },
];

export const PREVIEW_ADMIN_REPAIRS: Repair[] = [
  {
    ...PREVIEW_REPAIRS[0], repairId: "preview-admin-repair-1", repairNo: "FX20260817-001",
    returnDate: "2026-08-17", factoryId: "preview-admin-factory-1", factoryName: "旭之梦", warehouseReturnQuantity: 36,
    repairedQuantity: 18, scrappedQuantity: 2, returnedQuantity: 20,
    originalFilename: "质检单_20260817.xlsx", originalSizeBytes: 286720,
    lines: [
      { ...PREVIEW_REPAIRS[0].lines[0], inspectionLineId: 910001, productName: "探索家渔夫帽", propertiesValue: "米白/52", warehouseReturnQuantity: 20 },
      { ...PREVIEW_REPAIRS[0].lines[1], inspectionLineId: 910002, productName: "探索家渔夫帽", propertiesValue: "藏青/54", warehouseReturnQuantity: 16 },
    ],
    returnBatches: [{
      batchId: "preview-admin-batch-1", submittedAt:"2026-08-16T10:00:00+08:00", returnDate: "2026-08-16", submittedBy:"preview-factory-user",
      lines: [
        { variantId:"preview-admin-variant-1",sourceSkuId:"PREVIEW-001",sourceProductId:"PREVIEW-AP1",productName: "探索家渔夫帽", propertiesValue: "米白/52", warehouseReturnQuantity: 20, repairedQuantity: 12, scrappedQuantity: 1, returnedQuantity:13 },
        { variantId:"preview-admin-variant-2",sourceSkuId:"PREVIEW-002",sourceProductId:"PREVIEW-AP1",productName: "探索家渔夫帽", propertiesValue: "藏青/54", warehouseReturnQuantity: 16, repairedQuantity: 6, scrappedQuantity: 1, returnedQuantity:7 },
      ],
    }],
  },
  {
    ...PREVIEW_REPAIRS[0], repairId: "preview-admin-repair-2", repairNo: "FX20260816-002",
    returnDate: "2026-08-16", factoryId: "preview-admin-factory-2", factoryName: "龙腾", warehouseReturnQuantity: 48,
    repairedQuantity: 0, scrappedQuantity: 0, returnedQuantity: 0,
    originalFilename: "质检单_20260816.xlsx",
    lines: [{ ...PREVIEW_REPAIRS[0].lines[2], inspectionLineId: 920001, productName: "轻量防风马甲", propertiesValue: "军绿/110", warehouseReturnQuantity: 48 }],
  },
  {
    ...PREVIEW_REPAIRS[1], repairId: "preview-admin-repair-3", repairNo: "FX20260815-003",
    returnDate: "2026-08-15", factoryId: "preview-admin-factory-3", factoryName: "禹帆", warehouseReturnQuantity: 120,
    repairedQuantity: 78, scrappedQuantity: 12, returnedQuantity: 90,
  },
  {
    ...PREVIEW_REPAIRS[0], repairId: "preview-admin-repair-4", repairNo: "FX20260814-004",
    returnDate: "2026-08-14", factoryId: "preview-admin-factory-4", factoryName: "华盛", warehouseReturnQuantity: 60,
    repairedQuantity: 56, scrappedQuantity: 4, returnedQuantity: 60, status: "COMPLETED",
  },
];

export function previewRepair(repairId: string): Repair | undefined {
  return PREVIEW_REPAIRS.find((repair) => repair.repairId === repairId);
}

export function previewAdminRepair(repairId: string): Repair | undefined {
  return PREVIEW_ADMIN_REPAIRS.find((repair) => repair.repairId === repairId);
}
