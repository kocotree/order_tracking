import { factoryApi, type FactoryOption } from "../../api/factory";
import { isDevPreview, PREVIEW_APPLICATION, PREVIEW_FACTORIES } from "../../modules/dev-preview";
import { clearSession, storedUser } from "../../modules/identity/session";

Page({
  data: {
    realName: "",
    phoneMasked: "",
    position: "employee" as "owner" | "employee",
    keyword: "",
    factories: [] as FactoryOption[],
    selectedFactoryId: "",
    busy: false,
    previewMode: false,
  },

  onLoad(options: Record<string, string | undefined>) {
    if (isDevPreview(options)) {
      this.setData({
        previewMode: true,
        phoneMasked: PREVIEW_APPLICATION.phoneMasked,
        factories: PREVIEW_FACTORIES,
        ...(options.reapply === "1"
          ? {
              realName: PREVIEW_APPLICATION.realName,
              position: PREVIEW_APPLICATION.position as "owner" | "employee",
              selectedFactoryId: PREVIEW_APPLICATION.requestedFactoryId,
            }
          : {}),
      });
      return;
    }
    const user = storedUser();
    if (!user) {
      wx.reLaunch({ url: "/pages/auth/auth" });
      return;
    }
    this.setData({ phoneMasked: user.phoneMasked ?? "" });
    void this.loadFactories();
    if (options.reapply === "1") void this.loadPreviousApplication();
  },

  goBack() {
    if (this.data.previewMode) {
      wx.navigateBack();
      return;
    }
    wx.reLaunch({ url: "/pages/auth/auth" });
  },

  async loadPreviousApplication() {
    try {
      const application = await factoryApi.getMyApplication();
      if (!application) return;
      this.setData({
        realName: application.realName,
        position: application.position as "owner" | "employee",
        selectedFactoryId: application.requestedFactoryId,
      });
    } catch {
      wx.showToast({ title: "原申请加载失败", icon: "none" });
    }
  },

  async loadFactories() {
    try {
      const result = await factoryApi.listFactories(this.data.keyword);
      this.setData({ factories: result.items });
    } catch {
      clearSession();
      wx.reLaunch({ url: "/pages/auth/auth" });
    }
  },

  nameChanged(event: WechatMiniprogram.Input) {
    this.setData({ realName: event.detail.value });
  },

  keywordChanged(event: WechatMiniprogram.Input) {
    this.setData({ keyword: event.detail.value });
  },

  searchFactories() {
    if (this.data.previewMode) {
      const keyword = this.data.keyword.trim();
      this.setData({
        factories: PREVIEW_FACTORIES.filter((factory) =>
          `${factory.supplierNumber}${factory.factoryName}`.includes(keyword),
        ),
      });
      return;
    }
    void this.loadFactories();
  },

  selectPosition(event: WechatMiniprogram.TouchEvent) {
    this.setData({ position: event.currentTarget.dataset.position as "owner" | "employee" });
  },

  factoryChanged(event: WechatMiniprogram.PickerChange) {
    const factory = this.data.factories[Number(event.detail.value)];
    this.setData({ selectedFactoryId: factory?.factoryId ?? "" });
  },

  async submit() {
    if (!this.data.realName.trim()) {
      wx.showToast({ title: "请填写真实姓名", icon: "none" });
      return;
    }
    if (!this.data.selectedFactoryId) {
      wx.showToast({ title: "请选择系统已有工厂", icon: "none" });
      return;
    }
    if (this.data.previewMode) {
      wx.showToast({ title: "预览模式不会提交申请", icon: "none" });
      return;
    }
    this.setData({ busy: true });
    try {
      await factoryApi.submitApplication(
        this.data.realName.trim(),
        this.data.position,
        this.data.selectedFactoryId,
      );
      wx.redirectTo({ url: "/pages/factory-status/factory-status?status=pending" });
    } catch {
      wx.showToast({ title: "申请提交失败，请稍后重试", icon: "none" });
    } finally {
      this.setData({ busy: false });
    }
  },
});
