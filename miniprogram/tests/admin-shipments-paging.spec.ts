import { beforeEach, expect, it, vi } from "vitest";
const mocks=vi.hoisted(()=>({shipments:vi.fn(),repairs:vi.fn(),periods:vi.fn(),factories:vi.fn()}));
vi.mock("../api/shipments",()=>({shipmentApi:{adminPage:mocks.shipments}}));
vi.mock("../api/repairs",()=>({repairApi:{adminPage:mocks.repairs,adminPeriodOptions:mocks.periods}}));
vi.mock("../api/factory",()=>({factoryApi:{listFactories:mocks.factories}}));
vi.mock("../modules/identity/session",()=>({storedUser:()=>({role:"admin"}),clearSession:vi.fn()}));
type PageInstance={
 data:{activeTab:string;total:number;items:{shipmentId:string;productSummary:string;orderSummary:string}[];loading:boolean;hasMore:boolean;error:string;
  repairItems:{repairId:string}[];repairTotal:number;repairFactoryCount:number;periodOptions:string[];factoryOptions:{label:string;value:string}[]};
 setData(values:Record<string,unknown>,callback?:()=>void):void;
 onLoad(options:Record<string,string>):void; onShow():void; onReachBottom():void; onUnload():void; retry():void;
 selectTab(event:{currentTarget:{dataset:{tab:string}}}):void; keywordChanged(event:{detail:{value:string}}):void;
};
let page:PageInstance;
const flush=async()=>{for(let index=0;index<5;index++)await Promise.resolve();};
const shipment=(shipmentId:string)=>({shipmentId,shipmentNo:shipmentId,status:"SUBMITTED",receiptStatus:"UNRECEIVED",factoryId:"f1",factoryName:"甲工厂",businessDate:"2026-01-01",orderNos:"D-1",productNames:"外套、内衬",totalQuantity:3,totalBoxes:2});
const repair=(repairId:string)=>({repairId,repairNo:"2026.1-2026.6",status:"INCOMPLETE",returnDate:"2026-01-01",factoryId:"f1",factoryName:"甲工厂",warehouseReturnQuantity:10,repairedQuantity:4,scrappedQuantity:1,returnedQuantity:5});
beforeEach(()=>{
 vi.resetModules();
 mocks.shipments.mockReset(); mocks.shipments.mockResolvedValue({items:[],total:0});
 mocks.repairs.mockReset(); mocks.repairs.mockResolvedValue({items:[],total:0,factoryCount:0});
 mocks.periods.mockReset(); mocks.periods.mockResolvedValue({items:["2026.1-2026.6"]});
 mocks.factories.mockReset(); mocks.factories.mockResolvedValue({items:[{factoryId:"f1",factoryName:"甲工厂"}]});
 vi.stubGlobal("wx",{getDeviceInfo:()=>({platform:"ios"}),pageScrollTo:vi.fn(),showToast:vi.fn(),reLaunch:vi.fn(),stopPullDownRefresh:vi.fn(),navigateTo:vi.fn()});
 vi.stubGlobal("Page",(definition:PageInstance)=>{page={...definition,data:{...definition.data},setData(values,callback){Object.assign(this.data,values);callback?.();}};});
});

it("appends the next page of shipments when the list reaches the bottom", async()=>{
 mocks.shipments.mockResolvedValueOnce({items:Array.from({length:20},(_,index)=>shipment(`a${index}`)),total:30});
 mocks.shipments.mockResolvedValueOnce({items:[shipment("b0")],total:30});
 await import("../pages/admin-shipments/admin-shipments");
 page.onLoad({}); page.onShow(); await flush();
 expect(mocks.shipments.mock.lastCall?.[0]).toMatchObject({page:1,keyword:"",factory:"",dateFrom:"",dateTo:""});
 expect([page.data.items.length,page.data.total,page.data.hasMore]).toEqual([20,30,true]);
 expect(page.data.items[0]).toMatchObject({productSummary:"外套等2个产品",orderSummary:"D-1"});
 page.onReachBottom(); await flush();
 expect(mocks.shipments.mock.lastCall?.[0]).toMatchObject({page:2});
 expect(page.data.items.length).toBe(21);
 page.onUnload();
});

it("requests the server again when the keyword changes", async()=>{
 await import("../pages/admin-shipments/admin-shipments");
 page.onLoad({}); page.onShow(); await flush();
 page.keywordChanged({detail:{value:"外套"}}); await flush();
 expect(mocks.shipments.mock.lastCall?.[0]).toMatchObject({page:1,keyword:"外套"});
 expect(mocks.shipments).toHaveBeenCalledTimes(2);
});

it("loads paged repairs with the server factory count when the tab is opened", async()=>{
 mocks.repairs.mockResolvedValueOnce({items:[repair("r0")],total:1,factoryCount:4});
 await import("../pages/admin-shipments/admin-shipments");
 page.onLoad({}); page.onShow(); await flush();
 expect(page.data.periodOptions).toEqual(["全部周期","2026.1-2026.6"]);
 expect(page.data.factoryOptions).toEqual([{label:"全部工厂",value:""},{label:"甲工厂",value:"甲工厂"}]);
 page.selectTab({currentTarget:{dataset:{tab:"repairs"}}}); await flush();
 expect(mocks.repairs.mock.lastCall?.[0]).toMatchObject({page:1,status:"all",factories:"",period:""});
 expect([page.data.repairItems.length,page.data.repairTotal,page.data.repairFactoryCount]).toEqual([1,1,4]);
});

it("recovers from a failed first page when the error is tapped", async()=>{
 mocks.shipments.mockRejectedValueOnce(new Error("offline"));
 mocks.shipments.mockResolvedValueOnce({items:[shipment("a0")],total:1});
 await import("../pages/admin-shipments/admin-shipments");
 page.onLoad({}); page.onShow(); await flush();
 expect([page.data.error,page.data.items.length,page.data.loading]).toEqual(["加载失败，点击重试",0,false]);
 page.retry(); await flush();
 expect([page.data.error,page.data.items.length,page.data.total]).toEqual(["",1,1]);
});
