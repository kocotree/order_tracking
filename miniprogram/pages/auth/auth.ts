import { identityApi, wxLoginCode } from "../../api/identity";
import { requestNotificationSubscriptions } from "../../api/notifications";
import { isDevPreview } from "../../modules/dev-preview";
import {
  canRequestPhone,
  loginDestination,
  saveSession,
  updateStoredUser,
  type MiniLogin,
} from "../../modules/identity/session";

Page({
  data: {
    mode: "identifying" as "identifying" | "bind",
    agreementAccepted: false,
    bindingToken: "",
    busy: false,
  },

  onLoad(options: Record<string, string | undefined>) {
    if (isDevPreview(options)) {
      this.setData({ mode: "bind", busy: false });
      return;
    }
    void this.identify();
  },

  async identify() {
    this.setData({ mode: "identifying", busy: true });
    try {
      const result = await identityApi.wechatLogin(await wxLoginCode());
      if (result.status === "phone_required" && result.bindingToken) {
        this.setData({ mode: "bind", bindingToken: result.bindingToken, busy: false });
        return;
      }
      void this.continueWith(result);
    } catch {
      this.setData({ mode: "bind", busy: false });
      wx.showToast({ title: "身份识别失败，请稍后重试", icon: "none" });
    }
  },

  agreementChanged(event: WechatMiniprogram.CheckboxGroupChange) {
    this.setData({ agreementAccepted: event.detail.value.includes("accepted") });
  },

  requestAgreement() {
    wx.showToast({ title: "请先阅读并同意用户协议和隐私政策", icon: "none" });
  },

  async phoneAuthorized(event: WechatMiniprogram.ButtonGetPhoneNumber) {
    if (!canRequestPhone(this.data.agreementAccepted, this.data.bindingToken)) {
      this.requestAgreement();
      return;
    }
    if (event.detail.errMsg !== "getPhoneNumber:ok" || !event.detail.code) {
      wx.showToast({ title: "未取得手机号授权", icon: "none" });
      return;
    }
    this.setData({ busy: true });
    try {
      const result = await identityApi.bindPhone(this.data.bindingToken, event.detail.code);
      void this.continueWith(result);
    } catch {
      wx.showToast({ title: "手机号绑定失败，请稍后重试", icon: "none" });
      this.setData({ busy: false });
    }
  },

  openStatus(status: string, reason: string) {
    const query = `status=${encodeURIComponent(status)}&reason=${encodeURIComponent(reason)}`;
    wx.redirectTo({ url: `/pages/status/status?${query}` });
  },

  async continueWith(result: MiniLogin) {
    if (result.session && result.user) saveSession(result.session, result.user);
    else if (result.user) updateStoredUser(result.user);
    const destination = loginDestination(result);
    if (result.status === "authenticated" && result.user?.isEnabled && (result.user.role === "admin" || result.user.role === "factory")) {
      try { await requestNotificationSubscriptions(result.user.role); } catch { /* Rejection, close, and provider failure never block login. */ }
    }
    if (destination === "admin-orders") {
      wx.reLaunch({ url: "/pages/admin-orders/admin-orders" });
      return;
    }
    if (destination === "factory-tasks") {
      wx.reLaunch({ url: "/pages/factory-tasks/factory-tasks" });
      return;
    }
    if (destination === "factory-apply") {
      wx.redirectTo({ url: "/pages/factory-apply/factory-apply" });
      return;
    }
    if (destination === "factory-status") {
      const query = `status=${encodeURIComponent(result.status)}`;
      wx.redirectTo({ url: `/pages/factory-status/factory-status?${query}` });
      return;
    }
    this.openStatus(result.status, result.rejectionReason ?? "");
  },
});
