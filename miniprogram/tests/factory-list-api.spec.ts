import { beforeEach, expect, it, vi } from "vitest";
const request=vi.hoisted(()=>vi.fn());
vi.mock("../api/identity",()=>({authorizedRequest:request}));
beforeEach(()=>{request.mockReset();request.mockResolvedValue({items:[],total:0});});
it("omits unset dates and requests only the requested factory shipment page",async()=>{
 const {shipmentApi}=await import("../api/shipments");
 await shipmentApi.factoryPage({page:1,keyword:"A B%",shipDateFrom:undefined,shipDateTo:undefined});
 const url=request.mock.lastCall?.[0].url;
 expect(url).toBe("/factory/shipment-page?page=1&keyword=A%20B%25&pageSize=20");
 expect(request).toHaveBeenCalledTimes(1);
});
it("requests one repair page with full server filters",async()=>{
 const {repairApi}=await import("../api/repairs");
 await repairApi.factoryPage({page:2,keyword:"2026.8",status:"INCOMPLETE"});
 expect(request.mock.lastCall?.[0].url).toBe("/factory/repair-periods?page=2&keyword=2026.8&status=INCOMPLETE&pageSize=20");
 expect(request).toHaveBeenCalledTimes(1);
});
it("invalidates affected lists only after successful business writes",async()=>{
 const {shipmentApi}=await import("../api/shipments");
 const {repairApi}=await import("../api/repairs");
 const {factoryRevision}=await import("../modules/lists/factory-revisions");
 const order=factoryRevision("orders"), shipment=factoryRevision("shipments"), repair=factoryRevision("repairs");
 request.mockRejectedValueOnce(new Error());
 await expect(shipmentApi.submitDraft("id")).rejects.toThrow();
 expect(factoryRevision("orders")).toBe(order);
 await shipmentApi.submitDraft("id"); await shipmentApi.withdraw("id","reason",1,"key");
 expect(factoryRevision("orders")).toBe(order+2); expect(factoryRevision("shipments")).toBe(shipment+2);
 await repairApi.factorySubmitReturn("id",[],"key"); expect(factoryRevision("repairs")).toBe(repair+1);
});
