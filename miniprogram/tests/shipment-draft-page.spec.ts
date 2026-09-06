import { beforeEach, afterEach, expect, it, vi } from "vitest";
import type { CatalogItem, DraftBoxWrite, Shipment } from "../api/shipments";

type TestPage = {
  data: {step:number; boxCount:string; boxes:DraftBoxWrite[]; note:string; photos:{fileId?:number;localPath:string;downloadFailed?:boolean}[]; draftId:string; saveMessage:string; loading:boolean; ready:boolean};
  setData(value:Record<string,unknown>):void;
  onLoad(options:Record<string,string>):void;
  onUnload():void;
  photos?: unknown;
  addItem():void;
  closeBatchPacking():void;
  openBatchPacking():void;
  batchCountChanged(event:{detail:{value:string}}):void;
  applyBatchPacking():void;
  removeItem(event:{currentTarget:{dataset:{assignmentId:number}}}):void;
  previous():Promise<void>;
  submit():Promise<void>;
  next():Promise<void>;
  generateBoxes():Promise<void>;
  noteChanged(event:{detail:{value:string}}):void;
};
let page: TestPage;
let stored: Shipment | null;
let catalog: CatalogItem[];
let submitted: boolean;
let modalConfirm = true;
let modalChoices: boolean[] = [];

beforeEach(async () => {
  vi.resetModules();
  stored = null;
  catalog = [];
  submitted = false;
  modalConfirm = true;
  modalChoices = [];
  vi.stubGlobal("Page", (definition:TestPage) => {
    page = {...definition, data:structuredClone(definition.data), setData(value) { Object.assign(this.data,value); }};
  });
  vi.stubGlobal("wx", {
    getDeviceInfo: () => ({platform:"ios"}),
    getStorageSync: () => undefined,
    getAccountInfoSync: () => ({miniProgram:{envVersion:"develop"}}),
    showToast:vi.fn(), navigateBack:vi.fn(), redirectTo:vi.fn(),
    showModal:vi.fn((options) => options.success({confirm:modalChoices.shift() ?? modalConfirm,cancel:false})),
    downloadFile:vi.fn(options => options.success({statusCode:200,tempFilePath:"/cached-proof.png"})),
    request: (options:WechatMiniprogram.RequestOption) => {
      const url=options.url;
      let value:unknown; let statusCode=200;
      if(url.endsWith("/shipment-catalog")) value={items:catalog,total:catalog.length};
      else if(url.endsWith("/drafts/current")) {value=stored;statusCode=stored?200:404;}
      else if(options.method==="POST" && url.includes("/submit?")) {submitted=true;value={...stored,status:"SHIPPED"};}
      else if(options.method==="POST" && url.endsWith("/drafts")) {
        stored ||= {shipmentId:"draft-1",version:1,status:"DRAFT",boxes:[],files:[],note:"",totalBoxes:0} as unknown as Shipment;
        value=stored;
      } else if(options.method==="PUT") {
        const body=options.data as {version:number;boxes:DraftBoxWrite[];note:string};
        if(body.version !== stored?.version) {statusCode=409; value={message:"conflict"};}
        else {stored={...stored,...body,version:body.version+1,totalBoxes:body.boxes.length} as Shipment;value=stored;}
      } else if(options.method==="DELETE") {stored=null;statusCode=204;}
      else throw new Error(`Unexpected request ${options.method} ${url}`);
      options.success?.({data:structuredClone(value) as WechatMiniprogram.IAnyObject, statusCode,header:{},cookies:[],errMsg:"ok"} as unknown as Parameters<NonNullable<typeof options.success>>[0]);
    },
  });
  await import("../pages/factory-create-shipment/factory-create-shipment");
});
afterEach(() => {page?.onUnload?.();vi.unstubAllGlobals();});

it("saves empty boxes on entering packing and restores them after reopening", async () => {
  page.onLoad({});
  await vi.waitFor(() => expect(page.data.loading).toBe(false));
  page.setData({boxCount:"2"});
  await page.generateBoxes();
  await page.next();
  expect(stored?.boxes).toEqual([{boxNo:1,groupKey:null,items:[]},{boxNo:2,groupKey:null,items:[]}]);
  expect(page.data.step).toBe(2);
  page.onUnload();
  page.onLoad({});
  await vi.waitFor(() => expect(page.data.draftId).toBe("draft-1"));
  expect(page.data.boxes).toHaveLength(2);
});

it("does not navigate forward when saving fails", async () => {
  page.onLoad({});
  await vi.waitFor(() => expect(page.data.loading).toBe(false));
  page.setData({boxCount:"1"});
  await page.generateBoxes();
  vi.spyOn(wx,"request").mockImplementation(options => {options.fail?.({errMsg:"offline"} as WechatMiniprogram.RequestFailCallbackErr);return {} as WechatMiniprogram.RequestTask;});
  await page.next();
  expect(page.data.step).toBe(1);
  expect(page.data.saveMessage).toContain("未保存");
});

it("restores saved evidence and keeps the draft when restart confirmation is cancelled", async () => {
  stored = {shipmentId:"draft-1",version:3,status:"DRAFT",totalBoxes:1,note:"仓库备注",
    boxes:[{boxNo:1,groupKey:null,items:[]}],
    files:[{fileId:11,contentUrl:"/api/v1/shipment-files/11/content"}]} as unknown as Shipment;
  modalChoices=[false,false];
  page.onLoad({});
  await vi.waitFor(() => expect(page.data.ready).toBe(true));
  expect(page.data.note).toBe("仓库备注");
  expect(page.data.photos).toEqual([expect.objectContaining({fileId:11,localPath:"/cached-proof.png"})]);
  expect(stored?.shipmentId).toBe("draft-1");
});

it("abandons only after both restart choices and starts with no old contents", async () => {
  stored = {shipmentId:"draft-1",version:3,status:"DRAFT",totalBoxes:1,note:"旧备注",
    boxes:[{boxNo:1,groupKey:null,items:[]}],files:[]} as unknown as Shipment;
  modalChoices=[false,true];
  page.onLoad({});
  await vi.waitFor(() => expect(page.data.ready).toBe(true));
  expect(stored).toBeNull();
  expect(page.data.boxes).toEqual([]);
  expect(page.data.note).toBe("");
});

it("automatically saves note edits without requiring navigation", async () => {
  page.onLoad({});
  await vi.waitFor(() => expect(page.data.loading).toBe(false));
  page.setData({boxCount:"1"});
  await page.generateBoxes();
  await page.next();
  page.noteChanged({detail:{value:"下次继续"}});
  await vi.waitFor(() => expect(stored?.note).toBe("下次继续"),{timeout:1500});
  expect(page.data.saveMessage).toBe("草稿已保存");
});

it("flushes pending edits when leaving before the autosave delay", async () => {
  page.onLoad({});
  await vi.waitFor(() => expect(page.data.loading).toBe(false));
  page.setData({boxCount:"1"});
  await page.generateBoxes();
  await page.next();
  page.noteChanged({detail:{value:"刚填完就返回"}});
  page.onUnload();
  await vi.waitFor(() => expect(stored?.note).toBe("刚填完就返回"));
});


it("copies 33 boxes, saves and restores the group, and detaches only the edited box", async () => {
  page.onLoad({});
  await vi.waitFor(() => expect(page.data.ready).toBe(true));
  page.setData({boxCount:"33"});
  await page.generateBoxes();
  await page.next();
  const boxes = structuredClone(page.data.boxes);
  boxes[0].items=[{assignmentId:7,quantity:10}];
  page.setData({boxes});
  page.openBatchPacking();
  page.batchCountChanged({detail:{value:"32"}});
  page.applyBatchPacking();
  await vi.waitFor(() => expect(stored?.boxes[32].items).toEqual([{assignmentId:7,quantity:10}]),{timeout:1500});
  // A second attempt must not overwrite the already filled targets.
  page.openBatchPacking();
  page.batchCountChanged({detail:{value:"32"}});
  page.applyBatchPacking();
  expect(page.data.boxes[32].items).toEqual([{assignmentId:7,quantity:10}]);
  page.closeBatchPacking();
  const group = stored!.boxes[0].groupKey;
  expect(group).toBeTruthy();
  await page.previous();
  page.onUnload();
  page.onLoad({});
  await vi.waitFor(() => expect(page.data.ready).toBe(true));
  expect(page.data.boxes[32].groupKey).toBe(group);
  page.setData({currentBox:1});
  page.removeItem({currentTarget:{dataset:{assignmentId:7}}});
  expect(page.data.boxes[1]).toEqual(expect.objectContaining({groupKey:null,items:[]}));
  expect(page.data.boxes[0].items).toEqual([{assignmentId:7,quantity:10}]);
  expect(page.data.boxes[32].groupKey).toBe(group);
});


it("allows batch over-shipment but requires confirmation naming its order before submitting", async () => {
  catalog=[{assignmentId:7,orderId:"order-7",orderNo:"E81",productName:"风衣",propertiesValue:"蓝 / 120",pendingQuantity:15,assignedQuantity:15,shippedQuantity:0,contractShipDate:"2026-09-10"}];
  page.onLoad({});
  await vi.waitFor(() => expect(page.data.ready).toBe(true));
  page.setData({boxCount:"2"});
  await page.generateBoxes();
  await page.next();
  const boxes = structuredClone(page.data.boxes);
  boxes[0].items=[{assignmentId:7,quantity:10}];
  page.setData({boxes});
  page.openBatchPacking();
  page.batchCountChanged({detail:{value:"1"}});
  page.applyBatchPacking();
  expect(page.data.boxes[1].items).toEqual([{assignmentId:7,quantity:10}]);
  modalConfirm=false;
  await page.submit();
  expect(submitted).toBe(false);
  expect(wx.showModal).toHaveBeenCalledWith(expect.objectContaining({title:"确认多发",content:expect.stringContaining("E81")}));
  expect(wx.showModal).toHaveBeenCalledWith(expect.objectContaining({content:expect.stringContaining("多发 5 件")}));
  // Recheck on each submit: another shipment may have consumed the remainder.
  catalog[0].pendingQuantity=10;
  modalConfirm=false;
  await page.submit();
  expect(submitted).toBe(false);
  expect(wx.showModal).toHaveBeenLastCalledWith(expect.objectContaining({content:expect.stringContaining("多发 10 件")}));
  modalConfirm=true;
  await page.submit();
  expect(submitted).toBe(true);
});


it("detaches an individually added quantity from its packing group without changing peers", () => {
  page.setData({ready:true,currentBox:1,quantity:"3",selectedCatalog:{assignmentId:7},boxes:[
    {boxNo:1,groupKey:"g",items:[{assignmentId:7,quantity:10}],total:10},
    {boxNo:2,groupKey:"g",items:[{assignmentId:7,quantity:10}],total:10}
  ]});
  page.addItem();
  expect(page.data.boxes[1]).toEqual({boxNo:2,groupKey:null,items:[{assignmentId:7,quantity:13}],total:13});
  expect(page.data.boxes[0]).toEqual({boxNo:1,groupKey:"g",items:[{assignmentId:7,quantity:10}],total:10});
});
