import { authorizedRequest } from "./identity";

export interface ShipmentLine { assignmentId:number; orderId:string; orderNo:string; skuId:string; productName:string; propertiesValue:string; quantity:number }
export interface ShipmentBox { boxNo:number; groupKey:string|null; items:ShipmentLine[] }
export interface Shipment { shipmentId:string; shipmentNo:string|null; status:string; factoryId:string; factoryName:string; createdBy:string; preferredOrderId:string|null; businessDate:string|null; note:string; totalBoxes:number; totalQuantity:number; lines:ShipmentLine[]; boxes:ShipmentBox[]; createdAt:string; submittedAt:string|null }
export interface CatalogItem { assignmentId:number; orderId:string; orderNo:string; contractShipDate:string; productName:string; propertiesValue:string; assignedQuantity:number; shippedQuantity:number; pendingQuantity:number }
export interface DraftBoxWrite { boxNo:number; groupKey:string|null; items:{assignmentId:number;quantity:number}[] }

export const shipmentApi = {
  catalog: () => authorizedRequest<{items:CatalogItem[];total:number}>({url:"/factory/shipment-catalog",method:"GET"}),
  createDraft: (preferredOrderId?:string) => authorizedRequest<Shipment>({url:"/factory/shipments/drafts",method:"POST",data:{preferredOrderId:preferredOrderId||null}}),
  saveDraft: (shipmentId:string, boxes:DraftBoxWrite[], note:string) => authorizedRequest<Shipment>({url:`/factory/shipments/drafts/${encodeURIComponent(shipmentId)}`,method:"PUT",data:{boxes,note}}),
  submitDraft: (shipmentId:string) => authorizedRequest<Shipment>({url:`/factory/shipments/drafts/${encodeURIComponent(shipmentId)}/submit`,method:"POST",header:{"Idempotency-Key":`shipment-${Date.now()}`}}),
  factoryList: () => authorizedRequest<{items:Shipment[];total:number}>({url:"/factory/shipments",method:"GET"}),
  factoryGet: (shipmentId:string) => authorizedRequest<Shipment>({url:`/factory/shipments/${encodeURIComponent(shipmentId)}`,method:"GET"}),
  adminList: () => authorizedRequest<{items:Shipment[];total:number}>({url:"/admin/shipments",method:"GET"}),
  adminGet: (shipmentId:string) => authorizedRequest<Shipment>({url:`/admin/shipments/${encodeURIComponent(shipmentId)}`,method:"GET"}),
};
