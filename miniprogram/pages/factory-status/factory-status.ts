import { factoryApi, type FactoryApplication } from "../../api/factory";
import { identityApi } from "../../api/identity";
import { isDevPreview, PREVIEW_APPLICATION } from "../../modules/dev-preview";
import { storedUser } from "../../modules/identity/session";

Page({
  data: {
    status: "pending",
    application: null as FactoryApplication | null,
    factoryName: "",
    loading: false,
    previewMode: false,
  },

  onLoad(options: Record<string, string | undefined>) {
    const status = ["pending", "rejected", "disabled"].includes(options.status ?? "")
      ? options.status ?? "pending"
      : "pending";
    if (isDevPreview(options)) {
      this.setData({
        previewMode: true,
        status,
        factoryName: "禹帆",
        application: status === "disabled"
          ? null
          : {
              ...PREVIEW_APPLICATION,
              status,
              rejectionReason: status === "rejected" ? "申请信息与工厂登记信息不一致，请修改后重新提交。" : null,
              reviewedAt: status === "rejected" ? "2026-08-21 11:00" : null,
            },
      });
      return;
    }
    this.setData({ status, factoryName: storedUser()?.factoryName ?? "" });
    if (status === "disabled") return;
    void this.refresh();
  },

  async refresh() {
    if (this.data.previewMode) {
      wx.showToast({ title: "预览模式不会查询真实状态", icon: "none" });
      return;
    }
    this.setData({ loading: true });
    try {
      const application = await factoryApi.getMyApplication();
      if (!application) {
        wx.redirectTo({ url: "/pages/factory-apply/factory-apply" });
        return;
      }
      if (application.status === "approved") {
        wx.reLaunch({ url: "/pages/auth/auth" });
        return;
      }
      this.setData({ status: application.status, application });
    } catch {
      wx.reLaunch({ url: "/pages/auth/auth" });
    } finally {
      this.setData({ loading: false });
    }
  },

  reapply() {
    wx.redirectTo({
      url: this.data.previewMode
        ? "/pages/factory-apply/factory-apply?preview=1&reapply=1"
        : "/pages/factory-apply/factory-apply?reapply=1",
    });
  },

  logout() {
    if (this.data.previewMode) {
      wx.reLaunch({ url: "/pages/dev-preview/dev-preview?preview=1" });
      return;
    }
    void identityApi.logout().finally(() => {
      wx.reLaunch({ url: "/pages/status/status?status=logged-out" });
    });
  },
});
