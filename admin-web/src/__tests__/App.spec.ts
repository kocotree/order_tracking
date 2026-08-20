import { flushPromises, mount } from "@vue/test-utils";
import { createPinia } from "pinia";
import { afterEach, describe, expect, it, vi } from "vitest";

import App from "@/App.vue";
import type { User } from "@/api/client";
import { createAppRouter } from "@/router";

function response(payload: unknown, status = 200): Response {
  return new Response(status === 204 ? null : JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function user(overrides: Partial<User> = {}): User {
  return {
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
    capabilities: ["business.read", "mini.use"],
    ...overrides,
  };
}

afterEach(() => {
  vi.unstubAllGlobals();
  document.cookie = "ot_csrf=; Max-Age=0";
});

describe("administrator identity web", () => {
  it("redirects an anonymous visitor to the Feishu-only login page", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response({ code: "session_invalid" }, 401)));
    const pinia = createPinia();
    const router = createAppRouter(pinia, "/");
    await router.isReady();
    const wrapper = mount(App, { global: { plugins: [pinia, router] } });

    expect(router.currentRoute.value.name).toBe("login");
    expect(wrapper.text()).toContain("通过飞书登录");
    expect(wrapper.text()).not.toContain("手机号");
  });

  it("submits the confirmed phone-and-code application without a position field", async () => {
    const applicant = user({ role: null, phoneMasked: null, capabilities: [] });
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/v1/me")) return response(applicant);
      if (url.endsWith("/v1/admin-applications/me")) return response(null);
      if (url.endsWith("/v1/sms/challenges")) {
        return response({ challengeId: "challenge-1", phoneMasked: "138****5122", expiresAt: "2026-08-20T08:05:00" }, 201);
      }
      if (url.endsWith("/v1/admin-applications") && init?.method === "POST") {
        return response({ applicationId: "application-1", userId: applicant.userId, displayName: "煎饼", phoneMasked: "138****5122", status: "pending", rejectionReason: null, submittedAt: "2026-08-20T08:00:00", reviewedAt: null, reviewedBy: null, version: 1 }, 201);
      }
      throw new Error(`unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    document.cookie = "ot_csrf=csrf-test";
    const pinia = createPinia();
    const router = createAppRouter(pinia, "/admin-apply");
    await router.isReady();
    const wrapper = mount(App, { global: { plugins: [pinia, router] } });

    expect(wrapper.text()).toContain("管理员申请");
    expect(wrapper.text()).not.toContain("职位");
    await wrapper.get("#apply-phone").setValue("13812345122");
    await wrapper.get(".auth-secondary-button").trigger("click");
    await flushPromises();
    await wrapper.get("#apply-code").setValue("123456");
    await wrapper.get("form").trigger("submit");
    await flushPromises();

    expect(router.currentRoute.value.fullPath).toBe("/access-status/pending");
    const submitCall = fetchMock.mock.calls.find(([input, init]) =>
      String(input).endsWith("/v1/admin-applications") && init?.method === "POST",
    );
    expect(new Headers(submitCall?.[1]?.headers).get("X-CSRF-Token")).toBe("csrf-test");
  });

  it("keeps the super administrator application flow and shows all people entries", async () => {
    const superAdmin = user({ userId: "super-1", isSuperAdmin: true });
    let reviewed = false;
    const pending = { applicationId: "application-1", userId: "user-2", displayName: "小树", phoneMasked: "139****6677", status: "pending", rejectionReason: null, submittedAt: "2026-08-20T08:00:00", reviewedAt: null, reviewedBy: null, version: 1 };
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/v1/me")) return response(superAdmin);
      if (url.includes("/approve") && init?.method === "POST") {
        reviewed = true;
        return response({ ...pending, status: "approved", version: 2 });
      }
      if (url.includes("/v1/admin/admin-applications")) {
        return response({ items: reviewed ? [{ ...pending, status: "approved", version: 2 }] : [pending], total: 1 });
      }
      throw new Error(`unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const pinia = createPinia();
    const router = createAppRouter(pinia, "/people/admin-applications");
    await router.isReady();
    const wrapper = mount(App, { global: { plugins: [pinia, router] } });
    await flushPromises();

    expect(wrapper.text()).toContain("管理员申请");
    expect(wrapper.text()).toContain("工厂用户申请");
    expect(wrapper.text()).toContain("用户列表");
    await wrapper.get(".people-row-actions .text-button").trigger("click");
    expect(wrapper.text()).toContain("将获得普通管理员角色");
    await wrapper.get(".modal").trigger("submit");
    await flushPromises();
    expect(reviewed).toBe(true);
    expect(wrapper.text()).toContain("已通过");
  });

  it("keeps ordinary administrators out of super-administrator pages", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response(user())));
    const pinia = createPinia();
    const router = createAppRouter(pinia, "/people/admin-users");
    await router.isReady();

    expect(router.currentRoute.value.name).toBe("home");
  });

  it("lets an ordinary administrator maintain the confirmed factory fields", async () => {
    const factory = {
      factoryId: "factory-1",
      supplierNumber: "A10",
      factoryName: "禹帆",
      factoryCode: "YF",
      legalName: "温岭市新河禹帆制帽厂",
      address: "浙江省温岭市",
      legalRepresentative: "徐陈杰",
      isEnabled: true,
      version: 1,
      contractComplete: true,
      missingContractFields: [],
      contacts: [{ name: "王超", phone: "13858645122", displayOrder: 0, isPrimary: true }],
      connectedUsers: 1,
    };
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/v1/me")) return response(user());
      if (url.includes("/v1/admin/factories")) return response({ items: [factory], total: 1 });
      throw new Error(`unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const pinia = createPinia();
    const router = createAppRouter(pinia, "/factories");
    await router.isReady();
    const wrapper = mount(App, { global: { plugins: [pinia, router] } });
    await flushPromises();

    expect(wrapper.text()).toContain("A10");
    expect(wrapper.text()).toContain("禹帆");
    expect(wrapper.text()).toContain("王超");
    expect(wrapper.text()).not.toContain("委托代理人");
    expect(wrapper.text()).not.toContain("开户银行");
    expect(wrapper.text()).not.toContain("银行账号");
    expect(wrapper.text()).not.toContain("来源别名");
  });

  it("reviews a factory application from its detail dialog and confirms the binding factory", async () => {
    let approvedBody = "";
    const application = {
      applicationId: "application-factory-1",
      userId: "factory-user-1",
      realName: "张师傅",
      phoneMasked: "137****5678",
      position: "owner",
      requestedFactoryId: "factory-1",
      requestedFactoryName: "禹帆",
      boundFactoryId: null,
      boundFactoryName: null,
      status: "pending",
      submittedAt: "2026-08-20T08:00:00",
      reviewedBy: null,
      reviewedAt: null,
      rejectionReason: null,
      version: 1,
      factoryContacts: [{ name: "王超", phone: "13858645122", displayOrder: 0, isPrimary: true }],
    };
    const factory = {
      factoryId: "factory-1", supplierNumber: "A10", factoryName: "禹帆", factoryCode: "YF",
      legalName: "温岭市新河禹帆制帽厂", address: "浙江省温岭市", legalRepresentative: "徐陈杰",
      isEnabled: true, version: 1, contractComplete: true, missingContractFields: [],
      contacts: application.factoryContacts, connectedUsers: 0,
    };
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/v1/me")) return response(user());
      if (url.endsWith("/v1/admin/factory-applications")) return response({ items: [application], total: 1 });
      if (url.includes("/v1/admin/factories")) return response({ items: [factory], total: 1 });
      if (url.endsWith("/approve") && init?.method === "POST") {
        approvedBody = String(init.body);
        return response({ ...application, status: "approved", boundFactoryId: "factory-1", boundFactoryName: "禹帆", version: 2 });
      }
      throw new Error(`unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const pinia = createPinia();
    const router = createAppRouter(pinia, "/people/factory-applications");
    await router.isReady();
    const wrapper = mount(App, { global: { plugins: [pinia, router] } });
    await flushPromises();

    await wrapper.get(".people-table .text-button").trigger("click");
    expect(wrapper.text()).toContain("137****5678");
    expect(wrapper.text()).toContain("王超");
    await wrapper.get(".application-detail .primary-button").trigger("click");
    await flushPromises();
    await wrapper.get(".application-detail .primary-button").trigger("click");
    await flushPromises();

    expect(JSON.parse(approvedBody)).toEqual({ version: 1, factoryId: "factory-1" });
  });
});
