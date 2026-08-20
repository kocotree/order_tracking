import type { components } from "./generated";

const configuredBaseUrl = import.meta.env.VITE_API_BASE_URL?.trim();

export const apiBaseUrl = configuredBaseUrl || "/api";

export type AdminApplication = components["schemas"]["AdminApplicationResponse"];
export type AdminApplicationList = components["schemas"]["AdminApplicationListResponse"];
export type AdminUserList = components["schemas"]["AdminUserListResponse"];
export type SmsChallenge = components["schemas"]["SmsChallengeResponse"];
export type User = components["schemas"]["UserResponse"];

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string,
    message: string,
  ) {
    super(message);
  }
}

export function apiUrl(path: string): string {
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  return `${apiBaseUrl.replace(/\/$/, "")}${normalizedPath}`;
}

function readCookie(name: string): string | undefined {
  const prefix = `${encodeURIComponent(name)}=`;
  return document.cookie
    .split(";")
    .map((part) => part.trim())
    .find((part) => part.startsWith(prefix))
    ?.slice(prefix.length);
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !(init.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }
  if (init.method && init.method !== "GET") {
    const csrf = readCookie("ot_csrf");
    if (csrf) headers.set("X-CSRF-Token", decodeURIComponent(csrf));
  }
  const response = await fetch(apiUrl(path), {
    ...init,
    credentials: "include",
    headers,
  });
  if (!response.ok) {
    const payload = (await response.json().catch(() => ({}))) as {
      code?: string;
      message?: string;
    };
    throw new ApiError(
      response.status,
      payload.code ?? "request_failed",
      payload.message ?? "请求失败，请稍后重试",
    );
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export const feishuLoginUrl = (returnTo = "/") =>
  apiUrl(`/v1/auth/feishu/start?returnTo=${encodeURIComponent(returnTo)}`);

export const identityApi = {
  getMe: () => request<User>("/v1/me"),
  logout: () => request<void>("/v1/auth/logout", { method: "POST" }),
  sendSms: (phone: string) =>
    request<SmsChallenge>("/v1/sms/challenges", {
      method: "POST",
      body: JSON.stringify({ phone }),
    }),
  getMyApplication: () =>
    request<AdminApplication | null>("/v1/admin-applications/me"),
  submitApplication: (challengeId: string, verificationCode: string) =>
    request<AdminApplication>("/v1/admin-applications", {
      method: "POST",
      body: JSON.stringify({ challengeId, verificationCode }),
    }),
  listApplications: (status?: string) =>
    request<AdminApplicationList>(
      `/v1/admin/admin-applications${status ? `?status=${encodeURIComponent(status)}` : ""}`,
    ),
  approveApplication: (applicationId: string, version: number) =>
    request<AdminApplication>(
      `/v1/admin/admin-applications/${encodeURIComponent(applicationId)}/approve`,
      { method: "POST", body: JSON.stringify({ version }) },
    ),
  rejectApplication: (applicationId: string, version: number, reason: string) =>
    request<AdminApplication>(
      `/v1/admin/admin-applications/${encodeURIComponent(applicationId)}/reject`,
      { method: "POST", body: JSON.stringify({ version, reason }) },
    ),
  listAdminUsers: () => request<AdminUserList>("/v1/admin/users?role=admin"),
  setAdminEnabled: (userId: string, version: number, enabled: boolean) =>
    request<User>(
      `/v1/admin/users/${encodeURIComponent(userId)}/${enabled ? "enable" : "disable"}`,
      { method: "POST", body: JSON.stringify({ version }) },
    ),
};
