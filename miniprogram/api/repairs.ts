import type { components } from "./generated";
import { invalidateFactoryLists } from "../modules/lists/factory-revisions";
import { currentApiBaseUrl } from "./config";
import { authorizedRequest } from "./identity";
import { accessToken } from "../modules/identity/session";

export type RepairSummary = components["schemas"]["RepairSummaryResponse"];

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

export interface RepairAttachment { fileId:number; filename:string; sizeBytes:number }
export interface Repair {
  attachments?: RepairAttachment[];
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

export interface RepairDraftEntry { variantId: string; selected: boolean; repaired: string; scrapped: string }
export interface RepairDraft { version: number; entries: RepairDraftEntry[]; submissionKey: string }

async function listPeriods(role: "admin"|"factory"): Promise<RepairList> {
  const items:Repair[]=[];
  let total=0, page=1;
  do {
    const result=await authorizedRequest<RepairList>({url:`/${role}/repair-periods?pageSize=100&page=${page}`,method:"GET"});
    items.push(...result.items.map(item=>({...item, lines:[], specs:[], returnBatches:[], attachments:[]})));
    total=result.total;
    if(!result.items.length)break;
    page++;
  } while(items.length<total);
  return {items,total,page:1,pageSize:items.length};
}

export const repairApi = {
  getReturnDraft: (id: string) => authorizedRequest<RepairDraft>({ url: `/factory/repairs/${encodeURIComponent(id)}/return-draft`, method: "GET" }),
  saveReturnDraft: (id: string, version: number, entries: RepairDraftEntry[]) => authorizedRequest<RepairDraft>({ url: `/factory/repairs/${encodeURIComponent(id)}/return-draft`, method: "PUT", data: { version, entries } }),
  adminList: () => listPeriods("admin"),
  adminGet: (repairId: string) => authorizedRequest<Repair>({ url: `/admin/repairs/${encodeURIComponent(repairId)}`, method: "GET" }),
  factoryPage: (params: {keyword:string;status:string;page:number}) => {
    const query=Object.entries({...params,pageSize:20}).map(([key,value])=>`${key}=${encodeURIComponent(value)}`).join("&");
    return authorizedRequest<components["schemas"]["RepairSummaryListResponse"]>({url:`/factory/repair-periods?${query}`,method:"GET"});
  },
  factoryList: () => listPeriods("factory"),
  factoryGet: (repairId: string) => authorizedRequest<Repair>({ url: `/factory/repairs/${encodeURIComponent(repairId)}`, method: "GET" }),
  factorySubmitReturn: (repairId: string, lines: Array<{ variantId: string; repairedQuantity: number; scrappedQuantity: number }>, idempotencyKey: string, draftVersion?: number) => authorizedRequest<Repair>({
    url: `/factory/repairs/${encodeURIComponent(repairId)}/return-batches`,
    method: "POST",
    header: { "Idempotency-Key": idempotencyKey },
    data: { lines, draftVersion },
  }).then(result => { invalidateFactoryLists("repairs"); return result; }),
  download,
};
