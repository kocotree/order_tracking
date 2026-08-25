import { shipmentApi, type Shipment, type ShipmentBox, type ShipmentLine } from "../../api/shipments";
import { isDevPreview, PREVIEW_SHIPMENT } from "../../modules/dev-preview";

type LineGroup = { orderNo: string; total: number; items: ShipmentLine[]; expanded: boolean };
type BoxGroup = ShipmentBox & { total: number; expanded: boolean };

function buildLineGroups(lines: ShipmentLine[]): LineGroup[] {
  const groups = new Map<string, ShipmentLine[]>();
  lines.forEach((line) => groups.set(line.orderNo, [...(groups.get(line.orderNo) || []), line]));
  return Array.from(groups, ([orderNo, items]) => ({ orderNo, items, total: items.reduce((sum, item) => sum + item.quantity, 0), expanded: false }));
}

Page({
  data: { shipment: null as Shipment | null, lineGroups: [] as LineGroup[], boxGroups: [] as BoxGroup[], loading: true },
  onLoad(options: Record<string, string | undefined>) {
    if (isDevPreview(options)) { this.showShipment(PREVIEW_SHIPMENT); return; }
    if (options.shipmentId) void this.load(options.shipmentId);
  },
  showShipment(shipment: Shipment) {
    this.setData({ shipment, lineGroups: buildLineGroups(shipment.lines), boxGroups: shipment.boxes.map((box) => ({ ...box, total: box.items.reduce((sum, item) => sum + item.quantity, 0), expanded: false })), loading: false });
  },
  async load(id: string) {
    try { this.showShipment(await shipmentApi.factoryGet(id)); }
    catch { wx.showToast({ title: "发货单加载失败", icon: "none" }); this.setData({ loading: false }); }
  },
  toggleLineGroup(event: WechatMiniprogram.TouchEvent) {
    const orderNo = String(event.currentTarget.dataset.orderNo);
    this.setData({ lineGroups: this.data.lineGroups.map((group) => group.orderNo === orderNo ? { ...group, expanded: !group.expanded } : group) });
  },
  toggleBoxGroup(event: WechatMiniprogram.TouchEvent) {
    const boxNo = Number(event.currentTarget.dataset.boxNo);
    this.setData({ boxGroups: this.data.boxGroups.map((box) => box.boxNo === boxNo ? { ...box, expanded: !box.expanded } : box) });
  },
  goBack() { wx.navigateBack(); },
});
