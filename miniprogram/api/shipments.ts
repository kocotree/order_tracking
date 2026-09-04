import { currentApiBaseUrl } from "./config";
import { authorizedRequest } from "./identity";
import { accessToken } from "../modules/identity/session";

export interface ShipmentLine { assignmentId:number; orderId:string; orderNo:string; skuId:string; productName:string; propertiesValue:string; quantity:number; lineId?:number|null; returnedQuantity?:number; returnableQuantity?:number }
export interface ShipmentBox { boxNo:number; groupKey:string|null; items:ShipmentLine[] }
export interface ShipmentFile { fileId:number; filename:string; mimeType:string; sizeBytes:number; contentSha256:string; displayOrder:number; contentUrl:string }
export interface ShipmentVoidRequest { requestId:string; shipmentId:string; status:"PENDING"|"APPROVED"|"REJECTED"; reason:string; requestedBy:string; requestedByName:string; requestedAt:string; reviewedBy:string|null; reviewedAt:string|null; reviewComment:string|null }
export interface ShipmentReturnEvent { eventId:string; shipmentId:string; returnDate:string; reason:string; returnedBy:string; returnedAt:string; lines:{shipmentLineId:number;orderNo:string;quantity:number}[] }
export interface Shipment { shipmentId:string; shipmentNo:string|null; status:string; factoryId:string; factoryName:string; createdBy:string; preferredOrderId:string|null; businessDate:string|null; note:string; totalBoxes:number; totalQuantity:number; lines:ShipmentLine[]; boxes:ShipmentBox[]; files:ShipmentFile[]; voidRequest?:ShipmentVoidRequest|null; returnEvents?:ShipmentReturnEvent[]; createdAt:string; submittedAt:string|null }
export interface CatalogItem { assignmentId:number; orderId:string; orderNo:string; contractShipDate:string; productName:string; propertiesValue:string; assignedQuantity:number; shippedQuantity:number; pendingQuantity:number }
export interface DraftBoxWrite { boxNo:number; groupKey:string|null; items:{assignmentId:number;quantity:number}[] }

function parseUploadResponse(result: WechatMiniprogram.UploadFileSuccessCallbackResult): ShipmentFile {
  const payload = JSON.parse(result.data) as ShipmentFile & { message?: string };
  if (result.statusCode >= 200 && result.statusCode < 300) return payload;
  throw new Error(payload.message || "发货凭证上传失败");
}

function contentUrl(path: string): string {
  const relative = path.startsWith("/api/v1") ? path.slice("/api/v1".length) : path;
  return `${currentApiBaseUrl()}${relative.startsWith("/") ? relative : `/${relative}`}`;
}

export const shipmentApi = {
  catalog: () => authorizedRequest<{items:CatalogItem[];total:number}>({url:"/factory/shipment-catalog",method:"GET"}),
  createDraft: (preferredOrderId?:string) => authorizedRequest<Shipment>({url:"/factory/shipments/drafts",method:"POST",data:{preferredOrderId:preferredOrderId||null}}),
  saveDraft: (shipmentId:string, boxes:DraftBoxWrite[], note:string) => authorizedRequest<Shipment>({url:`/factory/shipments/drafts/${encodeURIComponent(shipmentId)}`,method:"PUT",data:{boxes,note}}),
  uploadFile: (shipmentId:string, filePath:string, idempotencyKey:string, onProgress:(progress:number)=>void) => new Promise<ShipmentFile>((resolve,reject) => {
    const task = wx.uploadFile({
      url:`${currentApiBaseUrl()}/factory/shipments/drafts/${encodeURIComponent(shipmentId)}/files`,
      filePath,
      name:"file",
      header:{Authorization:`Bearer ${accessToken() || ""}`,"Idempotency-Key":idempotencyKey},
      success(result) { try { resolve(parseUploadResponse(result)); } catch (error) { reject(error); } },
      fail:error => reject(new Error(error.errMsg)),
    });
    task.onProgressUpdate(result => onProgress(result.progress));
  }),
  removeFile: (shipmentId:string,fileId:number) => authorizedRequest<WechatMiniprogram.IAnyObject>({url:`/factory/shipments/drafts/${encodeURIComponent(shipmentId)}/files/${fileId}`,method:"DELETE"}),
  downloadFile: (file:ShipmentFile) => new Promise<string>((resolve,reject) => wx.downloadFile({
    url:contentUrl(file.contentUrl),
    header:{Authorization:`Bearer ${accessToken() || ""}`},
    success(result) { if(result.statusCode===200)resolve(result.tempFilePath); else reject(new Error("发货凭证加载失败")); },
    fail:error => reject(new Error(error.errMsg)),
  })),
  submitDraft: (shipmentId:string) => authorizedRequest<Shipment>({url:`/factory/shipments/drafts/${encodeURIComponent(shipmentId)}/submit`,method:"POST",header:{"Idempotency-Key":`shipment-${Date.now()}`}}),
  factoryList: () => authorizedRequest<{items:Shipment[];total:number}>({url:"/factory/shipments",method:"GET"}),
  factoryGet: (shipmentId:string) => authorizedRequest<Shipment>({url:`/factory/shipments/${encodeURIComponent(shipmentId)}`,method:"GET"}),
  requestVoid: (shipmentId:string, reason:string) => authorizedRequest<ShipmentVoidRequest>({url:`/factory/shipments/${encodeURIComponent(shipmentId)}/void-requests`,method:"POST",header:{"Idempotency-Key":`shipment-void-${Date.now()}`},data:{reason}}),
  adminList: () => authorizedRequest<{items:Shipment[];total:number}>({url:"/admin/shipments",method:"GET"}),
  adminGet: (shipmentId:string) => authorizedRequest<Shipment>({url:`/admin/shipments/${encodeURIComponent(shipmentId)}`,method:"GET"}),
};
