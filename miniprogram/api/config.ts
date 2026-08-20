export type WeChatEnvironment = "develop" | "trial" | "release";

const API_BASE_URLS: Record<WeChatEnvironment, string> = {
  develop: "http://127.0.0.1:8000/api/v1",
  trial: "https://api.example.invalid/api/v1",
  release: "https://api.example.invalid/api/v1",
};

export function apiBaseUrlFor(environment: WeChatEnvironment): string {
  return API_BASE_URLS[environment];
}

export function currentApiBaseUrl(): string {
  const environment = wx.getAccountInfoSync().miniProgram.envVersion || "develop";
  return apiBaseUrlFor(environment);
}
