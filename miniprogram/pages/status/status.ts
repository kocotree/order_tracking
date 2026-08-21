import { isIdentityStatus, type IdentityStatus } from "../../modules/identity/session";
import { isDevPreview } from "../../modules/dev-preview";

const CONTENT: Record<IdentityStatus, { mark: string; title: string; description: string; note: string; action: string }> = {
  identifying: { mark: "…", title: "正在识别身份", description: "正在通过微信身份确认管理员账号，请稍候。", note: "身份识别完成后将自动进入下一步", action: "" },
  pending: { mark: "审", title: "管理员申请审核中", description: "已匹配到网页端提交的管理员申请，审核通过后即可使用小程序。", note: "请等待最高管理员审核", action: "刷新状态" },
  rejected: { mark: "驳", title: "管理员申请未通过", description: "已匹配到未通过的管理员申请，小程序内不能重新提交申请。", note: "请前往管理员网页端重新申请", action: "" },
  unmatched: { mark: "!", title: "未找到管理员申请", description: "当前手机号没有匹配到网页端已验证的管理员申请。", note: "请先前往管理员网页端提交申请", action: "" },
  ambiguous: { mark: "!", title: "无法绑定管理员账号", description: "当前手机号无法唯一匹配管理员账号，系统不会自动合并身份。", note: "请联系最高管理员处理", action: "" },
  disabled: { mark: "停", title: "账号已停用", description: "已匹配的管理员账号当前处于停用状态，暂时无法查看业务数据。", note: "如需恢复使用，请联系最高管理员", action: "" },
  "logged-out": { mark: "退", title: "已退出登录", description: "当前登录会话已结束，微信与管理员账号的绑定仍然保留。", note: "重新登录不会再次授权手机号", action: "重新登录" },
};

Page({
  data: { status: "unmatched" as IdentityStatus, content: CONTENT.unmatched, reason: "", previewMode: false },
  onLoad(options: Record<string, string | undefined>) {
    const status = options.status && isIdentityStatus(options.status) ? options.status : "unmatched";
    this.setData({ status, content: CONTENT[status], reason: options.reason ?? "", previewMode: isDevPreview(options) });
  },
  act() {
    if (this.data.previewMode) {
      wx.showToast({ title: "预览模式不会查询真实状态", icon: "none" });
      return;
    }
    wx.reLaunch({ url: "/pages/auth/auth" });
  },
});
