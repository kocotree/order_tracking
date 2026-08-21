import { isDevPreview } from "../../modules/dev-preview";

interface PreviewItem {
  label: string;
  description: string;
  url: string;
}

Page({
  data: {
    items: [
      { label: "微信授权登录", description: "登录前入口页面", url: "/pages/auth/auth?preview=1" },
      { label: "未找到管理员申请", description: "身份未匹配状态", url: "/pages/status/status?status=unmatched&preview=1" },
      { label: "管理员申请审核中", description: "网页端申请等待审核", url: "/pages/status/status?status=pending&preview=1" },
      { label: "申请加入工厂", description: "工厂用户填写申请", url: "/pages/factory-apply/factory-apply?preview=1" },
      { label: "工厂申请审核中", description: "已提交申请的等待状态", url: "/pages/factory-status/factory-status?status=pending&preview=1" },
      { label: "工厂申请未通过", description: "拒绝原因与重新申请", url: "/pages/factory-status/factory-status?status=rejected&preview=1" },
      { label: "管理员个人中心", description: "最高管理员账号信息", url: "/pages/profile/profile?variant=admin&preview=1" },
      { label: "工厂用户个人中心", description: "所属工厂与职位信息", url: "/pages/profile/profile?variant=factory&preview=1" },
    ] satisfies PreviewItem[],
  },

  onLoad(options: Record<string, string | undefined>) {
    if (!isDevPreview(options)) wx.reLaunch({ url: "/pages/auth/auth" });
  },

  open(event: WechatMiniprogram.TouchEvent) {
    const url = event.currentTarget.dataset.url as string;
    if (url) wx.navigateTo({ url });
  },
});
