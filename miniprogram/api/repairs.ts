import { currentApiBaseUrl } from "./config";
import { authorizedRequest } from "./identity";
import { accessToken } from "../modules/identity/session";

export interface RepairLine {
  inspectionLineId: number;
  sourceRow: number;
  sourceOrder: number;
  boxNumber: string;
  sourceSkuId: string;
  productName: string;
  propertiesValue: string;
  warehouseReturnQuantity: number;
  reason: string | null;
}

export interface RepairReturnLine {
  variantId: string;
  sourceSkuId: string;
  sourceProductId: string;
  productName: string;
  propertiesValue: string;
  warehouseReturnQuantity: number;
  repairedQuantity: number;
  scrappedQuantity: number;
  returnedQuantity: number;
}

export interface RepairReturnBatch {
  batchId: string;
  submittedAt: string;
  returnDate: string;
  submittedBy: string;
  lines: RepairReturnLine[];
}

export interface RepairSpec extends RepairReturnLine {
  pendingQuantity: number;
}

export interface Repair {
  repairId: string;
  repairNo: string;
  status: "INCOMPLETE" | "COMPLETED";
  returnDate: string;
  factoryId: string;
  factoryName: string;
  warehouseReturnQuantity: number;
  repairedQuantity: number;
  scrappedQuantity: number;
  returnedQuantity: number;
  originalFileId: number;
  originalFilename: string;
  originalSizeBytes: number;
  createdAt: string;
  lines: RepairLine[];
  specs: RepairSpec[];
  returnBatches: RepairReturnBatch[];
}

export interface RepairList { items: Repair[]; total: number; page: number; pageSize: number }

function download(fileId: number): Promise<string> {
  return new Promise((resolve, reject) => {
    wx.downloadFile({
      url: `${currentApiBaseUrl()}/files/${fileId}/download`,
      header: { Authorization: `Bearer ${accessToken() || ""}` },
      success(result) {
        if (result.statusCode === 200) resolve(result.tempFilePath);
        else reject(new Error("质检附件下载失败"));
      },
      fail: reject,
    });
  });
}

export const repairApi = {
  adminList: () => authorizedRequest<RepairList>({ url: "/admin/repairs?pageSize=100", method: "GET" }),
  adminGet: (repairId: string) => authorizedRequest<Repair>({ url: `/admin/repairs/${encodeURIComponent(repairId)}`, method: "GET" }),
  factoryList: () => authorizedRequest<RepairList>({ url: "/factory/repairs?pageSize=100", method: "GET" }),
  factoryGet: (repairId: string) => authorizedRequest<Repair>({ url: `/factory/repairs/${encodeURIComponent(repairId)}`, method: "GET" }),
  factorySubmitReturn: (repairId: string, lines: Array<{ variantId: string; repairedQuantity: number; scrappedQuantity: number }>, idempotencyKey: string) => authorizedRequest<Repair>({
    url: `/factory/repairs/${encodeURIComponent(repairId)}/return-batches`,
    method: "POST",
    header: { "Idempotency-Key": idempotencyKey },
    data: { lines },
  }),
  download,
};
