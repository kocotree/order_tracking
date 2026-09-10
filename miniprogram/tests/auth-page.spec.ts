import { beforeEach, expect, it, vi } from "vitest";
const api = vi.hoisted(() => ({ wechatLogin: vi.fn(), bindPhone: vi.fn(), wxLoginCode: vi.fn() }));
vi.mock("../api/identity", () => ({ identityApi: api, wxLoginCode: api.wxLoginCode }));
vi.mock("../api/notifications", () => ({ requestNotificationSubscriptions: vi.fn() }));
type AuthPage = {
  data: { agreementAccepted: boolean; bindingToken: string; busy: boolean; mode: string };
  setData(values: Partial<AuthPage["data"]>): void;
  identify(): Promise<void>;
  phoneAuthorized(event: WechatMiniprogram.ButtonGetPhoneNumber): Promise<void>;
  requestAgreement(): void;
  retryLogin(): Promise<void>;
};
let page: AuthPage;
const phoneEvent = { detail: { errMsg: "getPhoneNumber:ok", code: "phone-code" } } as WechatMiniprogram.ButtonGetPhoneNumber;
beforeEach(async () => {
  vi.resetModules(); vi.clearAllMocks();
  api.wxLoginCode.mockResolvedValue("wx-code");
  api.wechatLogin.mockResolvedValue({ status: "phone_required", bindingToken: "new-attempt" });
  vi.stubGlobal("wx", { showToast: vi.fn(), reLaunch: vi.fn(), redirectTo: vi.fn(), setStorageSync: vi.fn() });
  vi.stubGlobal("Page", (definition: AuthPage) => {
    page = { ...definition, data: { ...definition.data }, setData(values) { Object.assign(this.data, values); } };
  });
  await import("../pages/auth/auth");
});
it("does not blame accepted agreement when identity preparation failed", async () => {
  page.data.agreementAccepted = true;
  await page.phoneAuthorized(phoneEvent);
  expect(wx.showToast).not.toHaveBeenCalledWith(expect.objectContaining({ title: "请先阅读并同意用户协议和隐私政策" }));
  expect(api.bindPhone).not.toHaveBeenCalled();
});
it("retries failed identification while retaining agreement", async () => {
  api.wechatLogin.mockRejectedValueOnce(new Error("unavailable"));
  await page.identify();
  expect(page.data.bindingToken).toBe("");
  expect(page.data.busy).toBe(false);
  page.data.agreementAccepted = true;
  await page.retryLogin();
  expect(page.data.bindingToken).toBe("new-attempt");
  expect(page.data.agreementAccepted).toBe(true);
  expect(api.wechatLogin).toHaveBeenCalledTimes(2);
});
it("blocks unaccepted agreement without requesting identity or phone", async () => {
  await page.retryLogin();
  await page.phoneAuthorized(phoneEvent);
  expect(api.wechatLogin).not.toHaveBeenCalled();
  expect(api.bindPhone).not.toHaveBeenCalled();
  expect(wx.showToast).toHaveBeenCalledWith(expect.objectContaining({ title: "请先阅读并同意用户协议和隐私政策" }));
});
it("does not submit while another request is active", async () => {
  page.data.agreementAccepted = true;
  page.data.bindingToken = "attempt";
  page.data.busy = true;
  await page.retryLogin();
  await page.phoneAuthorized(phoneEvent);
  expect(api.wechatLogin).not.toHaveBeenCalled();
  expect(api.bindPhone).not.toHaveBeenCalled();
});
it.each(["admin", "factory"])("continues authorized phone login for %s", async (role) => {
  page.data.agreementAccepted = true;
  page.data.bindingToken = "attempt";
  api.bindPhone.mockResolvedValue({ status: "authenticated", user: { role, isEnabled: true } });
  await page.phoneAuthorized(phoneEvent);
  await vi.waitFor(() => expect(wx.reLaunch).toHaveBeenCalledWith({ url: role === "admin" ? "/pages/admin-orders/admin-orders" : "/pages/factory-tasks/factory-tasks" }));
  expect(api.bindPhone).toHaveBeenCalledWith("attempt", "phone-code");
});
it("allows another attempt after denied phone authorization", async () => {
  page.data.agreementAccepted = true;
  page.data.bindingToken = "attempt";
  await page.phoneAuthorized({ detail: { errMsg: "getPhoneNumber:fail user deny" } } as WechatMiniprogram.ButtonGetPhoneNumber);
  expect(api.bindPhone).not.toHaveBeenCalled();
  expect(page.data.busy).toBe(false);
  expect(page.data.bindingToken).toBe("attempt");
});
