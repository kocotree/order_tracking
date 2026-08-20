import type { components } from "../../api/generated";

export type MiniLogin = components["schemas"]["MiniLoginResponse"];
export type MiniSession = components["schemas"]["SessionResponse"];
export type User = components["schemas"]["UserResponse"];

export type IdentityStatus =
  | "identifying"
  | "pending"
  | "rejected"
  | "unmatched"
  | "ambiguous"
  | "disabled"
  | "logged-out";

const ACCESS_TOKEN_KEY = "identity.accessToken";
const REFRESH_TOKEN_KEY = "identity.refreshToken";
const USER_KEY = "identity.user";

export function saveSession(session: MiniSession, user: User): void {
  wx.setStorageSync(ACCESS_TOKEN_KEY, session.accessToken);
  if (session.refreshToken) wx.setStorageSync(REFRESH_TOKEN_KEY, session.refreshToken);
  wx.setStorageSync(USER_KEY, user);
}

export function replaceSession(session: MiniSession): void {
  wx.setStorageSync(ACCESS_TOKEN_KEY, session.accessToken);
  if (session.refreshToken) wx.setStorageSync(REFRESH_TOKEN_KEY, session.refreshToken);
}

export function accessToken(): string {
  return wx.getStorageSync<string>(ACCESS_TOKEN_KEY) || "";
}

export function refreshToken(): string {
  return wx.getStorageSync<string>(REFRESH_TOKEN_KEY) || "";
}

export function storedUser(): User | null {
  return wx.getStorageSync<User>(USER_KEY) || null;
}

export function updateStoredUser(user: User): void {
  wx.setStorageSync(USER_KEY, user);
}

export function clearSession(): void {
  wx.removeStorageSync(ACCESS_TOKEN_KEY);
  wx.removeStorageSync(REFRESH_TOKEN_KEY);
  wx.removeStorageSync(USER_KEY);
}

export function isIdentityStatus(value: string): value is IdentityStatus {
  return [
    "identifying",
    "pending",
    "rejected",
    "unmatched",
    "ambiguous",
    "disabled",
    "logged-out",
  ].includes(value);
}

export function canRequestPhone(agreementAccepted: boolean, bindingToken: string): boolean {
  return agreementAccepted && bindingToken.length > 0;
}
