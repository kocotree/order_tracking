import type { DraftBoxWrite, Shipment } from "../api/shipments";

type DraftGateway = {
  createDraft(): Promise<Shipment>;
  saveDraft(id: string, boxes: DraftBoxWrite[], note: string, version: number): Promise<Shipment>;
};

// One page owns one session. Saves are serialized and use the last acknowledged version.
export class ShipmentDraftSession {
  current: Shipment | null = null;
  private latest: { boxes: DraftBoxWrite[]; note: string } | null = null;
  private savedKey = "";
  private pending: Promise<Shipment> | null = null;

  constructor(private readonly gateway: DraftGateway) {}

  resume(draft: Shipment) {
    this.current = draft;
    this.savedKey = JSON.stringify({ boxes: this.writeBoxes(draft), note: draft.note });
  }

  private writeBoxes(draft: Shipment): DraftBoxWrite[] {
    return draft.boxes.map(box => ({boxNo:box.boxNo, groupKey:box.groupKey,
      items:box.items.map(item => ({assignmentId:item.assignmentId, quantity:item.quantity}))}));
  }

  save(boxes: DraftBoxWrite[], note: string): Promise<Shipment> {
    this.latest = JSON.parse(JSON.stringify({boxes, note})) as typeof this.latest;
    if (!this.pending) this.pending = this.drain().finally(() => { this.pending=null; });
    return this.pending;
  }

  private async drain(): Promise<Shipment> {
    if (!this.current) {
      const draft = await this.gateway.createDraft();
      // A different page may have created a draft since our initial current-draft query.
      if (draft.boxes.length || draft.files.length || draft.version !== 1) {
        throw {statusCode:409, message:"已有发货草稿，请重新进入后选择继续填写"};
      }
      this.current = draft;
    }
    while (this.latest && JSON.stringify(this.latest) !== this.savedKey) {
      const value = this.latest;
      const result = await this.gateway.saveDraft(this.current.shipmentId, value.boxes, value.note, this.current.version);
      this.current = result;
      this.savedKey = JSON.stringify(value);
    }
    return this.current;
  }
}
