import { beforeEach, expect, it, vi } from "vitest";
const mocks=vi.hoisted(()=>({orders:vi.fn(),repairs:vi.fn(),shipments:vi.fn()}));
vi.mock("../api/orders",()=>({orderApi:{list:mocks.orders}}));
vi.mock("../api/repairs",()=>({repairApi:{factoryPage:mocks.repairs}}));
vi.mock("../api/shipments",()=>({shipmentApi:{factoryPage:mocks.shipments}}));
vi.mock("../modules/identity/session",()=>({storedUser:()=>({role:"factory"}),clearSession:vi.fn()}));
type PageInstance={
 data:{total:number;activeTab?:string;keyword:string;items:unknown[];repairItems?:unknown[]};
 setData(values:Record<string,unknown>,callback?:()=>void):void;
 onLoad(options:Record<string,string>):void; onShow():void; onUnload():void;
 selectTab(event:WechatMiniprogram.TouchEvent):void;
};
let page:PageInstance;
const flush=async()=>{await Promise.resolve();await Promise.resolve();await Promise.resolve();};
const deferred=<T>()=>{let resolve!:(value:T)=>void;const promise=new Promise<T>(r=>{resolve=r;});return {promise,resolve};};
beforeEach(()=>{
 vi.resetModules(); Object.values(mocks).forEach(mock=>{mock.mockReset();mock.mockResolvedValue({items:[],total:0});});
 vi.stubGlobal("wx",{getDeviceInfo:()=>({platform:"ios"}),pageScrollTo:vi.fn(),showToast:vi.fn(),reLaunch:vi.fn(),stopPullDownRefresh:vi.fn()});
 vi.stubGlobal("Page",(definition:PageInstance)=>{page={...definition,data:{...definition.data},setData(values,callback){Object.assign(this.data,values);callback?.();}};});
});
it.each(["orders","shipments"] as const)("%s loads once, keeps ordinary detail-return position, and invalidates in flight",async kind=>{
 const pending=deferred<{items:never[];total:number}>(); mocks[kind].mockReturnValueOnce(pending.promise);
 if(kind==="orders") await import("../pages/factory-tasks/factory-tasks"); else await import("../pages/factory-shipments/factory-shipments");
 page.onLoad({});page.onShow();expect(mocks[kind]).toHaveBeenCalledTimes(1);
 const {invalidateFactoryLists}=await import("../modules/lists/factory-revisions");
 invalidateFactoryLists(kind); page.onShow(); await flush();
 expect(mocks[kind]).toHaveBeenCalledTimes(2);
 expect(mocks[kind].mock.lastCall?.[0]).toMatchObject({page:1});
 expect(wx.pageScrollTo).toHaveBeenCalledWith({scrollTop:0,duration:0});
 pending.resolve({items:[],total:90});await flush();expect(page.data.total).toBe(0);
 vi.mocked(wx.pageScrollTo).mockClear();page.onShow();
 expect(mocks[kind]).toHaveBeenCalledTimes(2);expect(wx.pageScrollTo).not.toHaveBeenCalled();
 page.onUnload();
});
it("switches task tabs without previous responses overwriting active total",async()=>{
 const pending=deferred<{items:never[];total:number}>();mocks.orders.mockReturnValueOnce(pending.promise);
 await import("../pages/factory-tasks/factory-tasks");page.onLoad({});
 page.selectTab({currentTarget:{dataset:{tab:"repairs"}}} as unknown as WechatMiniprogram.TouchEvent);
 await flush();expect(mocks.repairs).toHaveBeenCalledTimes(1);
 pending.resolve({items:[],total:30});await flush();expect(page.data.total).toBe(0);
 const {invalidateFactoryLists}=await import("../modules/lists/factory-revisions");
 page.onShow();expect(mocks.repairs).toHaveBeenCalledTimes(1);
 invalidateFactoryLists("repairs");page.onShow();await flush();expect(mocks.repairs).toHaveBeenCalledTimes(2);
});
