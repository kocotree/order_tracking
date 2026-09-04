import type { DraftBoxWrite } from "../api/shipments";

export type ShipmentEvidenceStatus = "pending" | "uploading" | "uploaded" | "failed";

export interface ShipmentEvidencePhoto {
  localPath: string;
  uploadKey: string;
  fileId?: number;
  status: ShipmentEvidenceStatus;
  progress: number;
}

interface ShipmentEvidenceGateway<T> {
  createDraft(): Promise<{ shipmentId: string }>;
  saveDraft(shipmentId: string, boxes: DraftBoxWrite[], note: string): Promise<unknown>;
  uploadFile(
    shipmentId: string,
    photo: ShipmentEvidencePhoto,
    onProgress: (progress: number) => void,
  ): Promise<{ fileId: number }>;
  submitDraft(shipmentId: string): Promise<T>;
}

export async function submitShipmentWithEvidence<T>(options: {
  photos: ShipmentEvidencePhoto[];
  boxes: DraftBoxWrite[];
  note: string;
  gateway: ShipmentEvidenceGateway<T>;
  onPhotosChange: (photos: ShipmentEvidencePhoto[]) => void;
}): Promise<{ shipment: T; photos: ShipmentEvidencePhoto[] }> {
  const draft = await options.gateway.createDraft();
  await options.gateway.saveDraft(draft.shipmentId, options.boxes, options.note);
  let photos = options.photos.map((photo) => ({ ...photo }));

  const update = (index: number, patch: Partial<ShipmentEvidencePhoto>) => {
    photos = photos.map((photo, photoIndex) => photoIndex === index ? { ...photo, ...patch } : photo);
    options.onPhotosChange(photos);
  };

  for (let index = 0; index < photos.length; index += 1) {
    if (photos[index].fileId) continue;
    update(index, { status: "uploading", progress: 0 });
    try {
      const stored = await options.gateway.uploadFile(
        draft.shipmentId,
        photos[index],
        (progress) => update(index, { status: "uploading", progress }),
      );
      update(index, { fileId: stored.fileId, status: "uploaded", progress: 100 });
    } catch (error) {
      update(index, { status: "failed" });
      throw error;
    }
  }

  return {
    shipment: await options.gateway.submitDraft(draft.shipmentId),
    photos,
  };
}

export function newShipmentEvidencePhoto(localPath: string): ShipmentEvidencePhoto {
  return {
    localPath,
    uploadKey: `shipment-evidence-${Date.now()}-${Math.random().toString(36).slice(2)}`,
    status: "pending",
    progress: 0,
  };
}
