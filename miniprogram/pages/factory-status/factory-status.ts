import { factoryApi, type FactoryApplication } from "../../api/factory";
import { identityApi } from "../../api/identity";
import { storedUser } from "../../modules/identity/session";

Page({
  data: {
    status: "pending",
    application: null as FactoryApplication | null,
    factoryName: "",
    loading: false,
  },

  onLoad(options: Record<string, string | undefined>) {
    const status = ["pending", "rejected", "disabled"].includes(options.status ?? "")
      ? options.status ?? "pending"
      : "pending";
    this.setData({ status, factoryName: storedUser()?.factoryName ?? "" });
    if (status === "disabled") return;
    void this.refresh();
  },

  async refresh() {
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
    wx.redirectTo({ url: "/pages/factory-apply/factory-apply?reapply=1" });
  },

  logout() {
    void identityApi.logout().finally(() => {
      wx.reLaunch({ url: "/pages/status/status?status=logged-out" });
    });
  },
});
