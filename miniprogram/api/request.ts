import { currentApiBaseUrl } from "./config";

export interface ApiError {
  code: string;
  message: string;
  requestId?: string;
  statusCode?: number;
}

export function request<
  T extends string | WechatMiniprogram.IAnyObject | ArrayBuffer,
>(options: WechatMiniprogram.RequestOption<T>): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    wx.request<T>({
      ...options,
      url: `${currentApiBaseUrl()}${options.url.startsWith("/") ? options.url : `/${options.url}`}`,
      success(response) {
        if (response.statusCode >= 200 && response.statusCode < 300) {
          resolve(response.data);
          return;
        }
        reject({
          ...(response.data as ApiError),
          statusCode: response.statusCode,
        } satisfies ApiError);
      },
      fail(error) {
        reject({ code: "network_error", message: error.errMsg } satisfies ApiError);
      },
    });
  });
}
