import { returnFromShipmentDetail } from "../../modules/navigation";
import { shipmentApi, type Shipment, type ShipmentBox, type ShipmentFile, type ShipmentLine } from "../../api/shipments";
import { isDevPreview, PREVIEW_SHIPMENT } from "../../modules/dev-preview";
import { notificationApi } from "../../api/notifications";
import { notificationIdFrom } from "../../modules/notifications";

type LineGroup = { orderNo: string; total: number; items: ShipmentLine[]; expanded: boolean };
type BoxGroup = ShipmentBox & { total: number; expanded: boolean };
type ProofView = ShipmentFile & { localPath: string; status: "loading" | "ready" | "failed" };

function buildLineGroups(lines: ShipmentLine[]): LineGroup[] {
  const groups = new Map<string, ShipmentLine[]>();
  lines.forEach((line) => groups.set(line.orderNo, [...(groups.get(line.orderNo) || []), line]));
  return Array.from(groups, ([orderNo, items]) => ({ orderNo, items, total: items.reduce((sum, item) => sum + item.quantity, 0), expanded: false }));
}

Page({
  data: { shipment: null as Shipment | null, lineGroups: [] as LineGroup[], boxGroups: [] as BoxGroup[], proofs: [] as ProofView[], loading: true, notificationId:null as number|null },
  onLoad(options: Record<string, string | undefined>) {
    if (isDevPreview(options)) { this.showShipment(PREVIEW_SHIPMENT); return; }
    this.setData({notificationId:notificationIdFrom(options)}); if (options.shipmentId) void this.load(options.shipmentId);
  },
  showShipment(shipment: Shipment) {
    this.setData({ shipment, lineGroups: buildLineGroups(shipment.lines), boxGroups: shipment.boxes.map((box) => ({ ...box, total: box.items.reduce((sum, item) => sum + item.quantity, 0), expanded: false })), proofs: shipment.files.map(file => ({ ...file, localPath: "", status: "loading" })), loading: false });
    if (shipment.files.length) void this.loadProofs(shipment.files);
  },
  async loadProofs(files: ShipmentFile[]) {
    const proofs = await Promise.all(files.map(async file => {
      try { return { ...file, localPath: await shipmentApi.downloadFile(file), status: "ready" as const }; }
      catch { return { ...file, localPath: "", status: "failed" as const }; }
    }));
    this.setData({ proofs });
  },
  previewProof(event: WechatMiniprogram.TouchEvent) {
    const fileId = Number(event.currentTarget.dataset.fileId);
    const selected = this.data.proofs.find(item => item.fileId === fileId);
    const urls = this.data.proofs.filter(item => item.status === "ready").map(item => item.localPath);
    if (selected?.status === "ready") wx.previewImage({ current: selected.localPath, urls });
    else if (selected?.status === "failed") void this.retryProof(fileId);
  },
  async retryProof(fileId: number) {
    const file = this.data.proofs.find(item => item.fileId === fileId);
    if (!file) return;
    this.setData({ proofs: this.data.proofs.map(item => item.fileId === fileId ? { ...item, status: "loading" as const } : item) });
    try {
      const localPath = await shipmentApi.downloadFile(file);
      this.setData({ proofs: this.data.proofs.map(item => item.fileId === fileId ? { ...item, localPath, status: "ready" as const } : item) });
    } catch { this.setData({ proofs: this.data.proofs.map(item => item.fileId === fileId ? { ...item, status: "failed" as const } : item) }); }
  },
  async load(id: string) {
    try { this.showShipment(await shipmentApi.adminGet(id)); if(this.data.notificationId)await notificationApi.markRead(this.data.notificationId); }
    catch { wx.showToast({ title: this.data.notificationId?"内容已不可查看":"发货单加载失败", icon: "none" }); this.setData({ loading: false }); }
  },
  toggleLineGroup(event: WechatMiniprogram.TouchEvent) {
    const orderNo = String(event.currentTarget.dataset.orderNo);
    this.setData({ lineGroups: this.data.lineGroups.map((group) => group.orderNo === orderNo ? { ...group, expanded: !group.expanded } : group) });
  },
  toggleBoxGroup(event: WechatMiniprogram.TouchEvent) {
    const boxNo = Number(event.currentTarget.dataset.boxNo);
    this.setData({ boxGroups: this.data.boxGroups.map((box) => box.boxNo === boxNo ? { ...box, expanded: !box.expanded } : box) });
  },
  goBack() { returnFromShipmentDetail(); },
});
