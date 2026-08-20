import type { components } from "./generated";
import { currentApiBaseUrl } from "./config";
import { type ApiError, request } from "./request";
import {
  accessToken,
  clearSession,
  refreshToken,
  replaceSession,
  type MiniLogin,
  type MiniSession,
  type User,
} from "../modules/identity/session";

type Avatar = components["schemas"]["AvatarResponse"];

function authorizationHeader(): Record<string, string> {
  return accessToken() ? { Authorization: `Bearer ${accessToken()}` } : {};
}

async function refresh(): Promise<void> {
  const token = refreshToken();
  if (!token) throw { code: "session_invalid", message: "登录状态已失效" } satisfies ApiError;
  const session = await request<MiniSession>({
    url: "/mini/auth/refresh",
    method: "POST",
    data: { refreshToken: token },
  });
  replaceSession(session);
}

export async function authorizedRequest<T extends WechatMiniprogram.IAnyObject>(
  options: WechatMiniprogram.RequestOption<T>,
): Promise<T> {
  try {
    return await request<T>({ ...options, header: { ...options.header, ...authorizationHeader() } });
  } catch (error) {
    const apiError = error as ApiError;
    if (apiError.statusCode !== 401) throw error;
    await refresh();
    return request<T>({ ...options, header: { ...options.header, ...authorizationHeader() } });
  }
}

export const identityApi = {
  wechatLogin: (code: string) =>
    request<MiniLogin>({ url: "/mini/auth/wechat", method: "POST", data: { code } }),
  bindPhone: (bindingToken: string, phoneCode: string) =>
    request<MiniLogin>({
      url: "/mini/auth/phone",
      method: "POST",
      data: { bindingToken, phoneCode },
    }),
  getMe: () => authorizedRequest<User>({ url: "/me", method: "GET" }),
  logout: async () => {
    try {
      await authorizedRequest<WechatMiniprogram.IAnyObject>({
        url: "/mini/auth/logout",
        method: "POST",
      });
    } finally {
      clearSession();
    }
  },
  uploadAvatar: (filePath: string) =>
    new Promise<Avatar>((resolve, reject) => {
      wx.uploadFile({
        url: `${currentApiBaseUrl()}/mini/me/avatar`,
        filePath,
        name: "avatar",
        header: {
          ...authorizationHeader(),
          "Idempotency-Key": `mini-avatar-${Date.now()}`,
        },
        success(result) {
          if (result.statusCode >= 200 && result.statusCode < 300) {
            resolve(JSON.parse(result.data) as Avatar);
            return;
          }
          reject(JSON.parse(result.data) as ApiError);
        },
        fail(error) {
          reject({ code: "network_error", message: error.errMsg } satisfies ApiError);
        },
      });
    }),
  downloadAvatar: () =>
    new Promise<string>((resolve, reject) => {
      wx.downloadFile({
        url: `${currentApiBaseUrl()}/mini/me/avatar`,
        header: authorizationHeader(),
        success(result) {
          if (result.statusCode === 200) resolve(result.tempFilePath);
          else reject({ code: "avatar_download_failed", message: "头像读取失败" } satisfies ApiError);
        },
        fail(error) {
          reject({ code: "network_error", message: error.errMsg } satisfies ApiError);
        },
      });
    }),
};

export function wxLoginCode(): Promise<string> {
  return new Promise((resolve, reject) => {
    wx.login({
      success(result) {
        if (result.code) resolve(result.code);
        else reject(new Error("微信登录未返回 code"));
      },
      fail: reject,
    });
  });
}
