import { identityApi } from "../../api/identity";
import { notificationApi, requestNotificationSubscriptions } from "../../api/notifications";
import { isDevPreview, previewUser } from "../../modules/dev-preview";
import {
  clearSession,
  storedUser,
  updateStoredUser,
  type User,
} from "../../modules/identity/session";
import { adminNavigationItems, type NavigationItem } from "../../modules/navigation";

Page({
  data: {
    user: null as User | null,
    avatarFallback: "",
    avatarPath: "",
    avatarSheetOpen: false,
    uploading: false,
    previewMode: false,
    navigationItems: [] as NavigationItem[],
    unreadCount: 0,
    subscriptionBusy: false,
    subscriptionStatus: "去授权",
  },

  onShow() { if (!this.data.previewMode && this.data.user) void this.loadUnreadCount(); },

  onLoad(options: Record<string, string | undefined>) {
    if (isDevPreview(options)) {
      const user = previewUser(options.variant);
      this.setData({ previewMode: true, user, avatarFallback: user.displayName.slice(0, 1), navigationItems: this.navigationFor(user) });
      return;
    }
    void this.loadProfile();
  },

  async loadProfile() {
    try {
      const cached = storedUser();
      const user = await identityApi.getMe();
      updateStoredUser(user);
      this.setData({ user, avatarFallback: user.displayName.slice(0, 1), navigationItems: this.navigationFor(user) });
      void this.loadUnreadCount();
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

  async loadUnreadCount() {
    try { const result = await notificationApi.unreadCount(); this.setData({ unreadCount: result.count }); } catch { this.setData({ unreadCount: 0 }); }
  },

  openNotifications() { wx.navigateTo({ url: "/pages/notifications/notifications" }); },

  async requestSubscriptions() {
    const role = this.data.user?.role;
    if (role !== "admin" && role !== "factory") return;
    this.setData({ subscriptionBusy: true });
    try {
      const result = await requestNotificationSubscriptions(role);
      if (result === "accepted") this.setData({ subscriptionStatus:"本次已授权" });
      wx.showToast({ title: result === "accepted" ? "本次授权已记录" : result === "declined" ? "未取得本次订阅授权" : "订阅模板尚未配置", icon:"none" });
    } catch { wx.showToast({ title:"未完成订阅授权", icon:"none" }); }
    finally { this.setData({ subscriptionBusy:false }); }
  },

  navigationFor(user: User) {
    if (user.role === "admin") return adminNavigationItems();
    const primary = {
      key: "primary",
      label: "任务",
      path: "/pages/factory-tasks/factory-tasks",
      icon: "/assets/icons/admin-orders.svg",
      activeIcon: "/assets/icons/admin-orders-active.svg",
    };
    const shipments = { key: "shipments", label: "发货记录", path: "/pages/factory-shipments/factory-shipments", icon: "/assets/icons/factory-shipments.svg", activeIcon: "/assets/icons/factory-shipments-active.svg" };
    return [
      primary,
      shipments,
      {
        key: "profile",
        label: "我的",
        path: "/pages/profile/profile",
        icon: "/assets/icons/admin-profile.svg",
        activeIcon: "/assets/icons/admin-profile-active.svg",
      },
    ];
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

});
