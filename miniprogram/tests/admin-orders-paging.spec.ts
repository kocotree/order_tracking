import { beforeEach, expect, it, vi } from "vitest";
const mocks=vi.hoisted(()=>({orders:vi.fn(),factories:vi.fn()}));
vi.mock("../api/orders",()=>({orderApi:{list:mocks.orders}}));
vi.mock("../api/factory",()=>({factoryApi:{listFactories:mocks.factories}}));
vi.mock("../modules/identity/session",()=>({storedUser:()=>({role:"admin"}),clearSession:vi.fn()}));
type PageInstance={
 data:{total:number;items:{orderId:string}[];loading:boolean;loadingMore:boolean;hasMore:boolean;error:string;keyword:string};
 setData(values:Record<string,unknown>,callback?:()=>void):void;
 onLoad(options:Record<string,string>):void; onReachBottom():void; onUnload():void; retry():void; search():void;
};
let page:PageInstance;
const flush=async()=>{await Promise.resolve();await Promise.resolve();await Promise.resolve();};
const order=(orderId:string)=>({orderId,orderNo:orderId,detailMode:false,details:[],lines:[],factoryProgress:[],contractShipDates:[],displayStatus:"未完成",totalQuantity:1,shippedQuantity:0,pendingQuantity:1});
const listPage=(ids:string[],total:number)=>({items:ids.map(order),total});
beforeEach(()=>{
 vi.resetModules();
 mocks.orders.mockReset(); mocks.orders.mockResolvedValue(listPage([],0));
 mocks.factories.mockReset(); mocks.factories.mockResolvedValue({items:[]});
 vi.stubGlobal("wx",{getDeviceInfo:()=>({platform:"ios"}),pageScrollTo:vi.fn(),showToast:vi.fn(),reLaunch:vi.fn(),stopPullDownRefresh:vi.fn(),navigateTo:vi.fn()});
 vi.stubGlobal("Page",(definition:PageInstance)=>{page={...definition,data:{...definition.data},setData(values,callback){Object.assign(this.data,values);callback?.();}};});
});

it("appends the next page when the list reaches the bottom", async()=>{
 mocks.orders.mockResolvedValueOnce(listPage(Array.from({length:20},(_,index)=>`a${index}`),30));
 mocks.orders.mockResolvedValueOnce(listPage(["b0","b1"],30));
 await import("../pages/admin-orders/admin-orders");
 page.onLoad({}); await flush();
 expect(mocks.orders.mock.lastCall?.[0]).toMatchObject({page:1,pageSize:20});
 expect([page.data.items.length,page.data.total,page.data.hasMore]).toEqual([20,30,true]);
 page.onReachBottom(); await flush();
 expect(mocks.orders.mock.lastCall?.[0]).toMatchObject({page:2,pageSize:20});
 expect(page.data.items.map(item=>item.orderId)).toContain("b0");
 expect([page.data.items.length,page.data.loadingMore]).toEqual([22,false]);
 page.onUnload();
});

it("stops requesting once the loaded count reaches the total", async()=>{
 mocks.orders.mockResolvedValueOnce(listPage(["a0"],1));
 await import("../pages/admin-orders/admin-orders");
 page.onLoad({}); await flush();
 expect(page.data.hasMore).toBe(false);
 page.onReachBottom(); await flush();
 expect(mocks.orders).toHaveBeenCalledTimes(1);
});

it("recovers from a failed first page when the error is tapped", async()=>{
 mocks.orders.mockRejectedValueOnce(new Error("offline"));
 mocks.orders.mockResolvedValueOnce(listPage(["a0"],1));
 await import("../pages/admin-orders/admin-orders");
 page.onLoad({}); await flush();
 expect([page.data.error,page.data.items.length,page.data.loading]).toEqual(["加载失败，点击重试",0,false]);
 page.retry(); await flush();
 expect([page.data.error,page.data.items.length,page.data.total]).toEqual(["",1,1]);
});

it("drops an in-flight response when a new search starts", async()=>{
 let resolveFirst!:(value:ReturnType<typeof listPage>)=>void;
 mocks.orders.mockReturnValueOnce(new Promise(resolve=>{resolveFirst=resolve;}));
 mocks.orders.mockResolvedValueOnce(listPage(["b0"],1));
 await import("../pages/admin-orders/admin-orders");
 page.onLoad({});
 page.search(); await flush();
 expect(wx.pageScrollTo).toHaveBeenCalledWith({scrollTop:0,duration:0});
 resolveFirst(listPage(["a0","a1"],99)); await flush();
 expect(page.data.items.map(item=>item.orderId)).toEqual(["b0"]);
 expect(page.data.total).toBe(1);
});
