import type { FactoryApplication, FactoryOption } from "../api/factory";
import type { User } from "./identity/session";

export type PreviewOptions = Record<string, string | undefined>;

export function canUseDevPreview(preview: string | undefined, platform: string): boolean {
  return preview === "1" && platform === "devtools";
}

export function isDevPreview(options: PreviewOptions): boolean {
  return canUseDevPreview(options.preview, wx.getDeviceInfo().platform);
}

export const PREVIEW_FACTORIES: FactoryOption[] = [
  { factoryId: "preview-factory-1", supplierNumber: "A01", factoryName: "禹帆" },
  { factoryId: "preview-factory-2", supplierNumber: "A10", factoryName: "温岭市新河禹帆制帽厂" },
];

export const PREVIEW_APPLICATION: FactoryApplication = {
  applicationId: "preview-application",
  userId: "preview-factory-user",
  realName: "王超",
  phoneMasked: "138****5122",
  position: "employee",
  requestedFactoryId: "preview-factory-1",
  requestedFactoryName: "禹帆",
  boundFactoryId: null,
  boundFactoryName: null,
  factoryContacts: [],
  status: "pending",
  rejectionReason: null,
  reviewedAt: null,
  reviewedBy: null,
  submittedAt: "2026-08-21 10:30",
  version: 1,
};

const PREVIEW_USER_BASE: User = {
  userId: "preview-user",
  role: "admin",
  isSuperAdmin: true,
  isEnabled: true,
  displayName: "演示最高管理员",
  feishuAvatarUrl: null,
  miniAvatarExternalUrl: null,
  miniAvatarFileId: null,
  phoneMasked: "138****5122",
  factoryId: null,
  factoryName: null,
  factoryPosition: null,
  version: 1,
  capabilities: [],
};

export function previewUser(variant: string | undefined): User {
  if (variant === "factory") {
    return {
      ...PREVIEW_USER_BASE,
      userId: "preview-factory-user",
      role: "factory",
      isSuperAdmin: false,
      displayName: "王超",
      factoryId: "preview-factory-1",
      factoryName: "禹帆",
      factoryPosition: "employee",
    };
  }
  return PREVIEW_USER_BASE;
}
