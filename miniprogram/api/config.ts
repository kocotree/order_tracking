export type WeChatEnvironment = "develop" | "trial" | "release";

const API_BASE_URLS: Record<WeChatEnvironment, string> = {
  develop: "http://127.0.0.1:8000/api/v1",
  trial: "https://order-tracking-test.kktree.cn/api/v1",
  release: "https://order-tracking.kktree.cn/api/v1",
};

// Logical business categories may share one actual WeChat template ID.
export const SUBSCRIPTION_TEMPLATE_IDS = {
  admin_shipment: "qsM0bwEFQkMATPv-dPgwgtKw8XWdC8vJgfx5J8yqCNo",
  admin_repair: "gpFZ93n6vLFKUU5aCISc2CizJiCymGfKKTfl0e9HO6g",
  factory_status: "cSEC8Q5PUVz6NdcESpp-J4CGMLS8dScIK0CqsPRLzzY",
  factory_due: "GHS9jvL74feBeckR1W-J-xD-udAgXbGpoHIjgSsnKLw",
  factory_repair: "gpFZ93n6vLFKUU5aCISc2CizJiCymGfKKTfl0e9HO6g",
} as const;

export function apiBaseUrlFor(environment: WeChatEnvironment): string {
  return API_BASE_URLS[environment];
}

export function currentApiBaseUrl(): string {
  const environment = wx.getAccountInfoSync().miniProgram.envVersion || "develop";
  return apiBaseUrlFor(environment);
}
