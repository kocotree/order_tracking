export type WeChatEnvironment = "develop" | "trial" | "release";

const API_BASE_URLS: Record<WeChatEnvironment, string> = {
  develop: "http://127.0.0.1:8000/api/v1",
  trial: "https://api.example.invalid/api/v1",
  release: "https://api.example.invalid/api/v1",
};

// Actual template IDs are intentionally blank until the WeChat admin console
// choices have been accepted. Logical business categories may share one ID.
export const SUBSCRIPTION_TEMPLATE_IDS = {
  admin_shipment: "",
  admin_repair: "",
  factory_order: "",
  factory_repair: "",
} as const;

export function apiBaseUrlFor(environment: WeChatEnvironment): string {
  return API_BASE_URLS[environment];
}

export function currentApiBaseUrl(): string {
  const environment = wx.getAccountInfoSync().miniProgram.envVersion || "develop";
  return apiBaseUrlFor(environment);
}
