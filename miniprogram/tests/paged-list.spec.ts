import { describe, expect, it, vi } from "vitest";
import { PagedList, type ListState } from "../modules/lists/paged-list";

const deferred = <T>() => { let resolve!: (value:T)=>void; let reject!:()=>void; const promise=new Promise<T>((a,b)=>{resolve=a;reject=b;}); return {promise,resolve,reject}; };
const items=(start:number,count:number)=>Array.from({length:count},(_,i)=>({id:String(start+i)}));

describe("factory page loading",()=>{
  it("renders first page immediately, guards duplicate scrolls, deduplicates and stops at the end",async()=>{
    const states:ListState<{id:string}>[]=[];
    const second=deferred<{items:{id:string}[];total:number}>();
    const request=vi.fn().mockResolvedValueOnce({items:items(0,20),total:39}).mockReturnValueOnce(second.promise);
    const pager=new PagedList<{id:string}>(item=>item.id,state=>states.push(state));
    await pager.reset(request);
    expect(request).toHaveBeenCalledTimes(1); expect(states.at(-1)?.items).toHaveLength(20);
    const pending=pager.next(); void pager.next();
    expect(request).toHaveBeenCalledTimes(2); expect(states.at(-1)?.loadingMore).toBe(true);
    second.resolve({items:items(19,20),total:39}); await pending;
    expect(states.at(-1)?.items).toHaveLength(39); expect(states.at(-1)?.hasMore).toBe(false);
    await pager.next(); expect(request).toHaveBeenCalledTimes(2);
  });
  it("retains first page on append failure and retries the same page",async()=>{
    const update=vi.fn(), request=vi.fn().mockResolvedValueOnce({items:items(0,20),total:21}).mockRejectedValueOnce(new Error()).mockResolvedValueOnce({items:items(20,1),total:21});
    const pager=new PagedList<{id:string}>(item=>item.id,update);
    await pager.reset(request); await pager.next();
    expect(update.mock.lastCall?.[0]).toMatchObject({loading:false,loadingMore:false,error:"加载失败，点击重试"});
    expect(update.mock.lastCall?.[0].items).toHaveLength(20);
    await pager.next(); expect(request.mock.calls.map(call=>call[0])).toEqual([1,2,2]);
  });
  it("ignores old success and failure after a filter reset or page disposal",async()=>{
    const old=deferred<{items:{id:string}[];total:number}>(), update=vi.fn();
    const pager=new PagedList<{id:string}>(item=>item.id,update);
    const pending=pager.reset(()=>old.promise);
    await pager.reset(async()=>({items:items(50,1),total:1}));
    old.resolve({items:items(0,20),total:20}); await pending;
    expect(update.mock.lastCall?.[0].items).toEqual(items(50,1));
    const failure=deferred<{items:{id:string}[];total:number}>();
    const stale=pager.reset(()=>failure.promise); pager.dispose(); const count=update.mock.calls.length;
    failure.reject(); await stale; expect(update).toHaveBeenCalledTimes(count);
  });
});
