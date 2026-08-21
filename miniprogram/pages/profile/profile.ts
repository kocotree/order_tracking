import { identityApi } from "../../api/identity";
import { isDevPreview, previewUser } from "../../modules/dev-preview";
import {
  clearSession,
  storedUser,
  updateStoredUser,
  type User,
} from "../../modules/identity/session";

Page({
  data: {
    user: null as User | null,
    avatarFallback: "",
    avatarPath: "",
    avatarSheetOpen: false,
    uploading: false,
    previewMode: false,
  },

  onLoad(options: Record<string, string | undefined>) {
    if (isDevPreview(options)) {
      const user = previewUser(options.variant);
      this.setData({ previewMode: true, user, avatarFallback: user.displayName.slice(0, 1) });
      return;
    }
    void this.loadProfile();
  },

  async loadProfile() {
    try {
      const cached = storedUser();
      const user = await identityApi.getMe();
      updateStoredUser(user);
      this.setData({ user, avatarFallback: user.displayName.slice(0, 1) });
      if (user.role === "factory") return;
      if (user.miniAvatarFileId) {
        this.setData({ avatarPath: await identityApi.downloadAvatar() });
      } else {
        this.setData({ avatarPath: user.miniAvatarExternalUrl ?? cached?.miniAvatarExternalUrl ?? "" });
      }
    } catch {
      clearSession();
      wx.reLaunch({ url: "/pages/auth/auth" });
    }
  },

  openAvatarActions() {
    this.setData({ avatarSheetOpen: true });
  },

  closeAvatarActions() {
    this.setData({ avatarSheetOpen: false });
  },

  noop() {
    return;
  },

  viewAvatar() {
    if (!this.data.avatarPath) {
      wx.showToast({ title: "暂无可查看的头像", icon: "none" });
      return;
    }
    this.closeAvatarActions();
    wx.previewImage({ urls: [this.data.avatarPath], current: this.data.avatarPath });
  },

  async chooseAvatar(event: { detail: { avatarUrl: string } }) {
    const filePath = event.detail.avatarUrl;
    if (!filePath) return;
    if (this.data.previewMode) {
      this.setData({ avatarSheetOpen: false, avatarPath: filePath });
      wx.showToast({ title: "预览模式不会上传头像", icon: "none" });
      return;
    }
    this.setData({ avatarSheetOpen: false, uploading: true });
    try {
      await identityApi.uploadAvatar(filePath);
      const user = await identityApi.getMe();
      updateStoredUser(user);
      this.setData({ user, avatarPath: filePath });
      wx.showToast({ title: "头像已更新", icon: "success" });
    } catch {
      wx.showToast({ title: "头像上传失败，请重试", icon: "none" });
    } finally {
      this.setData({ uploading: false });
    }
  },

  logout() {
    wx.showModal({
      title: "退出登录",
      content: "退出后，下次进入仍会根据当前微信身份重新登录。确定退出吗？",
      confirmText: "确认退出",
      success: (result) => {
        if (!result.confirm) return;
        if (this.data.previewMode) {
          wx.reLaunch({ url: "/pages/dev-preview/dev-preview?preview=1" });
          return;
        }
        void identityApi.logout().finally(() => {
          wx.reLaunch({ url: "/pages/status/status?status=logged-out" });
        });
      },
    });
  },

  openOrders() {
    const url = this.data.user?.role === "factory"
      ? "/pages/factory-tasks/factory-tasks"
      : "/pages/admin-orders/admin-orders";
    wx.reLaunch({ url });
  },
});
