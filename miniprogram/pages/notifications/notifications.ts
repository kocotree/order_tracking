import { notificationApi, type NotificationItem } from "../../api/notifications";
import { notificationTarget } from "../../modules/notifications";

type NotificationView = NotificationItem & { categoryLabel:string; createdAtText:string };
const labels:Record<string,string> = { NEW_ORDER:"新订单", DUE_REMINDER:"合同出货", SHIPMENT:"发货", REPAIR:"返修", BUSINESS_RESULT:"处理结果" };
function view(item:NotificationItem):NotificationView { return { ...item, categoryLabel:labels[item.category] ?? "业务通知", createdAtText:new Date(item.createdAt).toLocaleString("zh-CN", { hour12:false }) }; }

Page({
  data: { status:"all" as "all"|"unread", page:1, items:[] as NotificationView[], total:0, hasMore:false, loading:true },
  onLoad(options:Record<string,string|undefined>) { const status = options.status === "unread" ? "unread" : "all"; this.setData({ status }); void this.load(true); },
  onShow() { if (!this.data.loading && this.data.items.length) void this.load(true); },
  onReachBottom() { if (this.data.hasMore && !this.data.loading) this.loadMore(); },
  async load(reset=false) { const page = reset ? 1 : this.data.page; this.setData({ loading:true }); try { const result = await notificationApi.list(this.data.status,page,10); const items = reset ? result.items.map(view) : [...this.data.items,...result.items.map(view)]; this.setData({ items,total:result.total,page,hasMore:items.length<result.total }); } catch { wx.showToast({ title:"通知加载失败",icon:"none" }); } finally { this.setData({ loading:false }); } },
  changeStatus(event:WechatMiniprogram.TouchEvent) { const status = event.currentTarget.dataset.status === "unread" ? "unread" : "all"; if (status === this.data.status) return; this.setData({ status,page:1,items:[] }); void this.load(true); },
  loadMore() { this.setData({ page:this.data.page+1 }); void this.load(false); },
  openNotification(event:WechatMiniprogram.TouchEvent) { const item=this.data.items[Number(event.currentTarget.dataset.index)]; if(!item)return; const url=notificationTarget(item.targetPath,item.targetType,item.targetId,item.notificationId,this.data.status); if(!url){wx.showToast({title:"内容已不可查看",icon:"none"});return;} wx.navigateTo({url,fail:()=>wx.showToast({title:"内容已不可查看",icon:"none"})}); },
});
