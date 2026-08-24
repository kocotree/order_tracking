import { beforeEach, describe, expect, it, vi } from "vitest";

import { identityApi } from "../api/identity";
import {
  accessToken,
  canRequestPhone,
  clearSession,
  isIdentityStatus,
  loginDestination,
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
    getAccountInfoSync: () => ({ miniProgram: { envVersion: "develop" } }),
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

  it("routes restricted factory identities through application states in the same mini program", () => {
    const factoryApplicant = {
      userId: "factory-applicant-1",
      role: null,
      isSuperAdmin: false,
      isEnabled: true,
      displayName: "微信用户",
      feishuAvatarUrl: null,
      miniAvatarExternalUrl: null,
      miniAvatarFileId: null,
      phoneMasked: "137****5678",
      factoryId: null,
      factoryName: null,
      factoryPosition: null,
      version: 1,
      capabilities: [],
    } satisfies User;
    expect(loginDestination({ status: "factory_application_required", user: factoryApplicant, session: null, bindingToken: null, rejectionReason: null })).toBe("factory-apply");
    expect(loginDestination({ status: "pending", user: factoryApplicant, session: null, bindingToken: null, rejectionReason: null })).toBe("factory-status");
    expect(loginDestination({ status: "rejected", user: factoryApplicant, session: null, bindingToken: null, rejectionReason: "资料不符" })).toBe("factory-status");
    expect(loginDestination({ status: "disabled", user: { ...factoryApplicant, role: "factory", factoryId: "factory-1", factoryName: null, factoryPosition: "employee", isEnabled: false }, session: null, bindingToken: null, rejectionReason: null })).toBe("factory-status");
    expect(loginDestination({ status: "authenticated", user: { ...factoryApplicant, role: "factory", factoryId: "factory-1", factoryName: "禹帆", factoryPosition: "employee" }, session: null, bindingToken: null, rejectionReason: null })).toBe("factory-tasks");
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
      factoryId: null,
      factoryName: null,
      factoryPosition: null,
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

  it("shares one refresh when concurrent authorized requests receive 401", async () => {
    storage.set("identity.accessToken", "expired-access");
    storage.set("identity.refreshToken", "refresh-token");
    let meCalls = 0;
    let refreshCalls = 0;
    vi.stubGlobal("wx", {
      setStorageSync: (key: string, value: unknown) => storage.set(key, value),
      getStorageSync: (key: string) => storage.get(key),
      removeStorageSync: (key: string) => storage.delete(key),
      getAccountInfoSync: () => ({ miniProgram: { envVersion: "develop" } }),
      request: (options: WechatMiniprogram.RequestOption) => {
        if (options.url.endsWith("/mini/auth/refresh")) {
          refreshCalls += 1;
          options.success?.({
            statusCode: 200,
            data: {
              accessToken: "renewed-access",
              refreshToken: "renewed-refresh",
              expiresAt: "2026-09-23T08:00:00",
            },
          } as unknown as WechatMiniprogram.RequestSuccessCallbackResult);
          return;
        }
        if (options.url.endsWith("/me")) {
          meCalls += 1;
          const authorized = options.header?.Authorization === "Bearer renewed-access";
          options.success?.({
            statusCode: authorized ? 200 : 401,
            data: authorized
              ? { userId: `user-${meCalls}`, role: "admin" }
              : { code: "session_invalid", message: "expired" },
          } as unknown as WechatMiniprogram.RequestSuccessCallbackResult);
        }
      },
    });

    const users = await Promise.all([identityApi.getMe(), identityApi.getMe()]);

    expect(refreshCalls).toBe(1);
    expect(meCalls).toBe(4);
    expect(users).toHaveLength(2);
  });
});
