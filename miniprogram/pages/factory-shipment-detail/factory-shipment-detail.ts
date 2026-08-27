import { shipmentApi, type Shipment, type ShipmentBox, type ShipmentLine } from "../../api/shipments";
import { isDevPreview, PREVIEW_SHIPMENT } from "../../modules/dev-preview";
import { notificationApi } from "../../api/notifications";
import { notificationIdFrom } from "../../modules/notifications";

type LineGroup = { orderNo: string; total: number; items: ShipmentLine[]; expanded: boolean };
type BoxGroup = ShipmentBox & { total: number; expanded: boolean };

function formatShanghaiDateTime(value: string | null): string {
  if (!value) return "—";
  const normalized = value
    .replace(/(\.\d{3})\d+/, "$1")
    .replace(/^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?(?:\.\d+)?)(?!Z|[+-]\d{2}:\d{2})$/, "$1Z");
  const timestamp = Date.parse(normalized);
  if (Number.isNaN(timestamp)) return value.replace("T", " ").slice(0, 16);
  const shanghai = new Date(timestamp + 8 * 60 * 60 * 1000);
  const pad = (part: number) => String(part).padStart(2, "0");
  return `${shanghai.getUTCFullYear()}-${pad(shanghai.getUTCMonth() + 1)}-${pad(shanghai.getUTCDate())} ${pad(shanghai.getUTCHours())}:${pad(shanghai.getUTCMinutes())}`;
}

function buildLineGroups(lines: ShipmentLine[]): LineGroup[] {
  const groups = new Map<string, ShipmentLine[]>();
  lines.forEach((line) => groups.set(line.orderNo, [...(groups.get(line.orderNo) || []), line]));
  return Array.from(groups, ([orderNo, items]) => ({ orderNo, items, total: items.reduce((sum, item) => sum + item.quantity, 0), expanded: false }));
}

Page({
  data: { shipment: null as Shipment | null, submittedAtText: "", lineGroups: [] as LineGroup[], boxGroups: [] as BoxGroup[], loading: true, withdrawStep: "" as ""|"form"|"confirm", withdrawReason: "", withdrawError: "", submitting: false, notificationId:null as number|null },
  onLoad(options: Record<string, string | undefined>) {
    if (isDevPreview(options)) { this.showShipment(PREVIEW_SHIPMENT); return; }
    this.setData({notificationId:notificationIdFrom(options)}); if (options.shipmentId) void this.load(options.shipmentId);
  },
  showShipment(shipment: Shipment) {
    this.setData({ shipment, submittedAtText: formatShanghaiDateTime(shipment.submittedAt), lineGroups: buildLineGroups(shipment.lines), boxGroups: shipment.boxes.map((box) => ({ ...box, total: box.items.reduce((sum, item) => sum + item.quantity, 0), expanded: false })), loading: false });
  },
  async load(id: string) {
    try { this.showShipment(await shipmentApi.factoryGet(id)); if(this.data.notificationId)await notificationApi.markRead(this.data.notificationId); }
    catch { wx.showToast({ title:this.data.notificationId?"内容已不可查看":"发货单加载失败", icon: "none" }); this.setData({ loading: false }); }
  },
  toggleLineGroup(event: WechatMiniprogram.TouchEvent) {
    const orderNo = String(event.currentTarget.dataset.orderNo);
    this.setData({ lineGroups: this.data.lineGroups.map((group) => group.orderNo === orderNo ? { ...group, expanded: !group.expanded } : group) });
  },
  toggleBoxGroup(event: WechatMiniprogram.TouchEvent) {
    const boxNo = Number(event.currentTarget.dataset.boxNo);
    this.setData({ boxGroups: this.data.boxGroups.map((box) => box.boxNo === boxNo ? { ...box, expanded: !box.expanded } : box) });
  },
  openWithdraw() { this.setData({ withdrawStep: "form", withdrawReason: "", withdrawError: "" }); },
  closeWithdraw() { if (!this.data.submitting) this.setData({ withdrawStep: "", withdrawError: "" }); },
  stopPropagation() {},
  updateWithdrawReason(event: WechatMiniprogram.Input) { this.setData({ withdrawReason: String(event.detail.value), withdrawError: "" }); },
  nextWithdraw() { const reason = this.data.withdrawReason.trim(); if (!reason) { this.setData({ withdrawError: "请填写撤回原因" }); return; } this.setData({ withdrawReason: reason, withdrawStep: "confirm" }); },
  async confirmWithdraw() {
    const shipment = this.data.shipment; if (!shipment || this.data.submitting) return;
    this.setData({ submitting: true, withdrawError: "" });
    try { await shipmentApi.requestVoid(shipment.shipmentId, this.data.withdrawReason); await this.load(shipment.shipmentId); this.setData({ withdrawStep: "", submitting: false }); wx.showToast({ title: "撤回申请已提交", icon: "success" }); }
    catch { this.setData({ submitting: false, withdrawError: "撤回申请提交失败" }); }
  },
  goBack() { wx.navigateBack(); },
});
