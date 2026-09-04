import { describe, expect, it, vi } from "vitest";

import { submitShipmentWithEvidence, type ShipmentEvidencePhoto } from "../modules/shipment-evidence";

describe("factory shipment evidence submission", () => {
  it("does not submit a formal shipment until every selected image uploads and safely retries", async () => {
    const submitDraft = vi.fn().mockResolvedValue({ shipmentId: "shipment-1", status: "SHIPPED" });
    const uploadFile = vi.fn()
      .mockResolvedValueOnce({ fileId: 11 })
      .mockRejectedValueOnce(new Error("upload failed"));
    const gateway = {
      createDraft: vi.fn().mockResolvedValue({ shipmentId: "shipment-1" }),
      saveDraft: vi.fn().mockResolvedValue({ shipmentId: "shipment-1" }),
      uploadFile,
      submitDraft,
    };
    const states: ShipmentEvidencePhoto[][] = [];
    const photos: ShipmentEvidencePhoto[] = [
      { localPath: "/tmp/proof-1.jpg", uploadKey: "proof-1", status: "pending", progress: 0 },
      { localPath: "/tmp/proof-2.jpg", uploadKey: "proof-2", status: "pending", progress: 0 },
    ];

    await expect(submitShipmentWithEvidence({
      photos,
      boxes: [],
      note: "",
      gateway,
      onPhotosChange: (value) => states.push(value),
    })).rejects.toThrow("upload failed");

    expect(submitDraft).not.toHaveBeenCalled();
    expect(states.at(-1)).toEqual([
      expect.objectContaining({ fileId: 11, status: "uploaded", progress: 100 }),
      expect.objectContaining({ status: "failed" }),
    ]);

    uploadFile.mockResolvedValueOnce({ fileId: 12 });
    const retried = await submitShipmentWithEvidence({
      photos: states.at(-1)!,
      boxes: [],
      note: "",
      gateway,
      onPhotosChange: (value) => states.push(value),
    });

    expect(uploadFile).toHaveBeenCalledTimes(3);
    expect(uploadFile.mock.calls.at(-1)?.[1]).toMatchObject({ uploadKey: "proof-2" });
    expect(submitDraft).toHaveBeenCalledTimes(1);
    expect(retried.photos.map((item) => item.fileId)).toEqual([11, 12]);
  });
});
