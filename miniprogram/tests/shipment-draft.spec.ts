import { describe, expect, it, vi } from "vitest";
import { ShipmentDraftSession } from "../modules/shipment-draft";
import type { Shipment } from "../api/shipments";

const draft = (version = 1): Shipment => ({ shipmentId:"draft-1", version, status:"DRAFT", boxes:[], files:[], note:"" } as unknown as Shipment);
const boxes = [{boxNo:1, groupKey:null, items:[]}];

describe("shipment draft saving", () => {
  it("preserves newer edits made while an empty-box save is still pending", async () => {
    let complete!: (value: Shipment) => void;
    const gateway = {
      createDraft: async () => draft(),
      saveDraft: vi.fn().mockImplementationOnce(() => new Promise<Shipment>(resolve => { complete=resolve; }))
        .mockResolvedValueOnce({...draft(3), boxes, note:"新备注"}),
    };
    const session = new ShipmentDraftSession(gateway);
    const first = session.save(boxes, "旧备注");
    await vi.waitFor(() => expect(gateway.saveDraft).toHaveBeenCalled());
    const next = session.save(boxes, "新备注");
    complete({...draft(2), boxes, note:"旧备注"});
    await Promise.all([first,next]);
    expect(session.current?.note).toBe("新备注");
    expect(gateway.saveDraft.mock.calls.map(call => call[3])).toEqual([1,2]);
  });

  it("keeps the original version after a failed save and never silently rebases a conflict", async () => {
    const gateway = {createDraft:async () => draft(), saveDraft:vi.fn().mockRejectedValue({statusCode:409})};
    const session = new ShipmentDraftSession(gateway);
    session.resume(draft(4));
    await expect(session.save(boxes,"本机编辑")).rejects.toEqual({statusCode:409});
    expect(session.current?.version).toBe(4);
    await expect(session.save(boxes,"重试")).rejects.toEqual({statusCode:409});
    expect(gateway.saveDraft.mock.calls.map(call => call[3])).toEqual([4,4]);
  });
});

it("never overwrites an existing draft returned after another page wins creation", async () => {
  const gateway = {createDraft:async () => ({...draft(2),boxes,note:"另一页面"}),saveDraft:vi.fn()};
  const session=new ShipmentDraftSession(gateway);
  await expect(session.save(boxes,"本页")).rejects.toMatchObject({statusCode:409});
  expect(gateway.saveDraft).not.toHaveBeenCalled();
});
