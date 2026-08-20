import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  accessToken,
  canRequestPhone,
  clearSession,
  isIdentityStatus,
  refreshToken,
  saveSession,
  storedUser,
  type User,
} from "../modules/identity/session";

const storage = new Map<string, unknown>();

beforeEach(() => {
  storage.clear();
  vi.stubGlobal("wx", {
    setStorageSync: (key: string, value: unknown) => storage.set(key, value),
    getStorageSync: (key: string) => storage.get(key),
    removeStorageSync: (key: string) => storage.delete(key),
  });
});

describe("mini-program identity session", () => {
  it("maps every confirmed identity status and rejects unknown values", () => {
    for (const status of [
      "identifying",
      "pending",
      "rejected",
      "unmatched",
      "ambiguous",
      "disabled",
      "logged-out",
    ]) {
      expect(isIdentityStatus(status)).toBe(true);
    }
    expect(isIdentityStatus("factory-application")).toBe(false);
  });

  it("does not allow phone authorization before both agreement and binding token", () => {
    expect(canRequestPhone(false, "binding-token")).toBe(false);
    expect(canRequestPhone(true, "")).toBe(false);
    expect(canRequestPhone(true, "binding-token")).toBe(true);
  });

  it("stores revocable mini tokens and the shared internal user, then clears all", () => {
    const user: User = {
      userId: "user-1",
      role: "admin",
      isSuperAdmin: false,
      isEnabled: true,
      displayName: "煎饼",
      feishuAvatarUrl: null,
      miniAvatarExternalUrl: null,
      miniAvatarFileId: null,
      phoneMasked: "138****5122",
      version: 1,
      capabilities: ["mini.use"],
    };
    saveSession(
      {
        accessToken: "access-token",
        refreshToken: "refresh-token",
        expiresAt: "2026-08-20T08:15:00",
      },
      user,
    );

    expect(accessToken()).toBe("access-token");
    expect(refreshToken()).toBe("refresh-token");
    expect(storedUser()?.userId).toBe("user-1");
    clearSession();
    expect(accessToken()).toBe("");
    expect(refreshToken()).toBe("");
    expect(storedUser()).toBeNull();
  });
});
