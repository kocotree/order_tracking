import type { components } from "./generated";

const configuredBaseUrl = import.meta.env.VITE_API_BASE_URL?.trim();

export const apiBaseUrl = configuredBaseUrl || "/api";

export type AdminApplication = components["schemas"]["AdminApplicationResponse"];
export type AdminApplicationList = components["schemas"]["AdminApplicationListResponse"];
export type AdminUserList = components["schemas"]["AdminUserListResponse"];
export type Factory = components["schemas"]["FactoryResponse"];
export type FactoryApplication = components["schemas"]["FactoryApplicationResponse"];
export type FactoryApplicationList = components["schemas"]["FactoryApplicationListResponse"];
export type FactoryList = components["schemas"]["FactoryListResponse"];
export type FactoryWrite = components["schemas"]["FactoryWrite"];
export type ProductList = components["schemas"]["ProductListResponse"];
export type ProductListItem = components["schemas"]["ProductListItemResponse"];
export type Order = components["schemas"]["OrderResponse"];
export type OrderList = components["schemas"]["OrderListResponse"];
export type DashboardOrders = components["schemas"]["DashboardResponse"];
export type DraftCreate = components["schemas"]["app__api__orders__DraftCreate"];
export type DraftUpdate = components["schemas"]["DraftUpdate"];
export type AuditLogList = components["schemas"]["AuditLogListResponse"];
export type ImportRun = components["schemas"]["ImportRunResponse"];
export type ImportCandidate = components["schemas"]["CandidateResponse"];
export type ImportCandidateList = components["schemas"]["CandidateListResponse"];
export type BatchConfirmResult = components["schemas"]["BatchConfirmResponse"];
export type User = components["schemas"]["UserResponse"];
export type ContractFactoryStatus = components["schemas"]["ContractFactoryStatusResponse"];
export type ContractFactoryStatusList = components["schemas"]["ContractFactoryStatusListResponse"];
export type ContractExport = components["schemas"]["ContractExportResponse"];

export interface ShipmentLine {
  assignmentId: number;
  orderId: string;
  orderNo: string;
  skuId: string;
  productName: string;
  propertiesValue: string;
  quantity: number;
}

export interface ShipmentBox {
  boxNo: number;
  groupKey: string | null;
  items: ShipmentLine[];
}

export interface Shipment {
  shipmentId: string;
  shipmentNo: string | null;
  status: string;
  factoryId: string;
  factoryName: string;
  createdBy: string;
  preferredOrderId: string | null;
  businessDate: string | null;
  note: string;
  totalBoxes: number;
  totalQuantity: number;
  lines: ShipmentLine[];
  boxes: ShipmentBox[];
  createdAt: string;
  submittedAt: string | null;
}

export interface ShipmentList { items: Shipment[]; total: number }

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

async function apiError(response: Response): Promise<ApiError> {
  const payload = (await response.json().catch(() => ({}))) as {
    code?: string;
    message?: string;
  };
  return new ApiError(
    response.status,
    payload.code ?? "request_failed",
    payload.message ?? "请求失败，请稍后重试",
  );
}

let activeRefresh: Promise<void> | null = null;

function refreshWebSession(): Promise<void> {
  if (activeRefresh) return activeRefresh;
  activeRefresh = fetch(apiUrl("/v1/auth/refresh"), {
    method: "POST",
    credentials: "include",
  })
    .then(async (response) => {
      if (!response.ok) throw await apiError(response);
    })
    .finally(() => {
      activeRefresh = null;
    });
  return activeRefresh;
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const send = async (): Promise<Response> => {
    const headers = new Headers(init.headers);
    if (init.body && !(init.body instanceof FormData)) {
      headers.set("Content-Type", "application/json");
    }
    if (init.method && init.method !== "GET") {
      const csrf = readCookie("ot_csrf");
      if (csrf) headers.set("X-CSRF-Token", decodeURIComponent(csrf));
    }
    return fetch(apiUrl(path), {
      ...init,
      credentials: "include",
      headers,
    });
  };

  let response = await send();
  if (response.status === 401) {
    await refreshWebSession();
    response = await send();
  }
  if (!response.ok) {
    throw await apiError(response);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

async function download(path: string, filename: string): Promise<void> {
  const apiRelativePath = path.startsWith("/api/") ? path.slice(4) : path;
  const send = () => fetch(apiUrl(apiRelativePath), { credentials: "include" });
  let response = await send();
  if (response.status === 401) {
    await refreshWebSession();
    response = await send();
  }
  if (!response.ok) throw await apiError(response);
  const href = URL.createObjectURL(await response.blob());
  const anchor = document.createElement("a");
  anchor.href = href;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(href);
}

export const feishuLoginUrl = (returnTo = "/") =>
  apiUrl(`/v1/auth/feishu/start?returnTo=${encodeURIComponent(returnTo)}`);

export const identityApi = {
  getMe: () => request<User>("/v1/me"),
  logout: () => request<void>("/v1/auth/logout", { method: "POST" }),
  getMyApplication: () =>
    request<AdminApplication | null>("/v1/admin-applications/me"),
  submitApplication: () =>
    request<AdminApplication>("/v1/admin-applications", {
      method: "POST",
      body: JSON.stringify({}),
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
  listFactories: (keyword = "", contractStatus = "all", accessStatus = "all") =>
    request<FactoryList>(
      `/v1/admin/factories?keyword=${encodeURIComponent(keyword)}&contractStatus=${encodeURIComponent(contractStatus)}&accessStatus=${encodeURIComponent(accessStatus)}`,
    ),
  createFactory: (payload: FactoryWrite) =>
    request<Factory>("/v1/admin/factories", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  updateFactory: (factoryId: string, payload: Omit<FactoryWrite, "supplierNumber"> & { version: number }) =>
    request<Factory>(`/v1/admin/factories/${encodeURIComponent(factoryId)}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  listFactoryApplications: (status?: string) =>
    request<FactoryApplicationList>(
      `/v1/admin/factory-applications${status ? `?status=${encodeURIComponent(status)}` : ""}`,
    ),
  approveFactoryApplication: (applicationId: string, version: number, factoryId: string) =>
    request<FactoryApplication>(
      `/v1/admin/factory-applications/${encodeURIComponent(applicationId)}/approve`,
      { method: "POST", body: JSON.stringify({ version, factoryId }) },
    ),
  rejectFactoryApplication: (applicationId: string, version: number, reason: string) =>
    request<FactoryApplication>(
      `/v1/admin/factory-applications/${encodeURIComponent(applicationId)}/reject`,
      { method: "POST", body: JSON.stringify({ version, reason }) },
    ),
  listFactoryUsers: () => request<AdminUserList>("/v1/admin/users?role=factory"),
  setFactoryUserEnabled: (userId: string, version: number, enabled: boolean) =>
    request<User>(
      `/v1/admin/users/${encodeURIComponent(userId)}/${enabled ? "enable" : "disable"}`,
      { method: "POST", body: JSON.stringify({ version }) },
    ),
  listProducts: (params: {
    keyword?: string;
    page?: number;
    pageSize?: number;
    sortBy?: "iId" | "skuId" | "name" | "propertiesValue";
    sortOrder?: "asc" | "desc";
  } = {}) => {
    const query = new URLSearchParams({
      keyword: params.keyword ?? "",
      page: String(params.page ?? 1),
      pageSize: String(params.pageSize ?? 10),
      sortBy: params.sortBy ?? "iId",
      sortOrder: params.sortOrder ?? "asc",
    });
    return request<ProductList>(`/v1/admin/products?${query.toString()}`);
  },
};

function idempotencyHeaders(): HeadersInit {
  return { "Idempotency-Key": crypto.randomUUID() };
}

export const orderApi = {
  list: (params: {
    keyword?: string;
    status?: string;
    category?: string;
    factoryId?: string;
    factoryIds?: string[];
    trackers?: string[];
    shipDateFrom?: string;
    shipDateTo?: string;
    sortBy?: string;
    includeDrafts?: boolean;
    page?: number;
    pageSize?: number;
  } = {}) => {
    const query = new URLSearchParams({
      keyword: params.keyword ?? "",
      status: params.status ?? "all",
      sortBy: params.sortBy ?? "priority",
      includeDrafts: String(params.includeDrafts ?? true),
      page: String(params.page ?? 1),
      pageSize: String(params.pageSize ?? 20),
    });
    if (params.category) query.set("category", params.category);
    if (params.factoryId) query.set("factoryId", params.factoryId);
    for (const factoryId of params.factoryIds ?? []) query.append("factoryIds", factoryId);
    for (const tracker of params.trackers ?? []) query.append("trackers", tracker);
    if (params.shipDateFrom) query.set("shipDateFrom", params.shipDateFrom);
    if (params.shipDateTo) query.set("shipDateTo", params.shipDateTo);
    return request<OrderList>(`/v1/orders?${query.toString()}`);
  },
  get: (orderId: string) => request<Order>(`/v1/orders/${encodeURIComponent(orderId)}`),
  dashboard: () => request<DashboardOrders>("/v1/admin/dashboard/orders"),
  auditLogs: (orderId: string) =>
    request<AuditLogList>(`/v1/admin/orders/${encodeURIComponent(orderId)}/audit-logs`),
  createDraft: (payload: DraftCreate) =>
    request<Order>("/v1/admin/orders", { method: "POST", body: JSON.stringify(payload) }),
  saveDraft: (orderId: string, payload: DraftUpdate) =>
    request<Order>(`/v1/admin/orders/${encodeURIComponent(orderId)}`, {
      method: "PUT",
      body: JSON.stringify(payload),
    }),
  publish: (orderId: string, version: number) =>
    request<Order>(`/v1/admin/orders/${encodeURIComponent(orderId)}/publish`, {
      method: "POST",
      headers: idempotencyHeaders(),
      body: JSON.stringify({ version }),
    }),
  withdraw: (orderId: string) =>
    request<Order>(`/v1/admin/orders/${encodeURIComponent(orderId)}/withdraw`, {
      method: "POST",
      headers: idempotencyHeaders(),
    }),
  delete: (orderId: string) =>
    request<void>(`/v1/admin/orders/${encodeURIComponent(orderId)}`, {
      method: "DELETE",
      headers: idempotencyHeaders(),
    }),
  complete: (orderId: string) =>
    request<Order>(`/v1/admin/orders/${encodeURIComponent(orderId)}/complete`, {
      method: "POST",
      headers: idempotencyHeaders(),
    }),
  reopen: (orderId: string, reason: string) =>
    request<Order>(`/v1/admin/orders/${encodeURIComponent(orderId)}/reopen`, {
      method: "POST",
      headers: idempotencyHeaders(),
      body: JSON.stringify({ reason }),
    }),
};

export const contractApi = {
  list: (orderId: string) =>
    request<ContractFactoryStatusList>(
      `/v1/admin/orders/${encodeURIComponent(orderId)}/contracts`,
    ),
  export: (orderId: string, factoryId: string, signingDate: string) =>
    request<ContractExport>(
      `/v1/admin/orders/${encodeURIComponent(orderId)}/contracts/${encodeURIComponent(factoryId)}/exports`,
      {
        method: "POST",
        headers: idempotencyHeaders(),
        body: JSON.stringify({ signingDate }),
      },
    ),
  download: (value: ContractExport) => download(value.downloadUrl, value.filename),
};

export const shipmentApi = {
  list: () => request<ShipmentList>("/v1/admin/shipments"),
  get: (shipmentId: string) =>
    request<Shipment>(`/v1/admin/shipments/${encodeURIComponent(shipmentId)}`),
};

export const orderImportApi = {
  createRun: () => request<ImportRun>("/v1/admin/import-runs", { method: "POST", headers: idempotencyHeaders() }),
  latestRun: () => request<ImportRun | null>("/v1/admin/import-runs/latest"),
  getRun: (runId: string) =>
    request<ImportRun>(`/v1/admin/import-runs/${encodeURIComponent(runId)}`),
  list: (params: {
    status?: "PENDING" | "IMPORTED";
    keyword?: string;
    category?: string;
    factoryNames?: string[];
    trackers?: string[];
    validationState?: string;
    sortBy?: string;
    sortOrder?: "asc" | "desc";
    page?: number;
    pageSize?: number;
  } = {}) => {
    const query = new URLSearchParams({
      status: params.status ?? "PENDING",
      keyword: params.keyword ?? "",
      page: String(params.page ?? 1),
      pageSize: String(params.pageSize ?? 20),
      sortBy: params.sortBy ?? "updatedAt",
      sortOrder: params.sortOrder ?? "desc",
    });
    if (params.category) query.set("category", params.category);
    if (params.validationState) query.set("validationState", params.validationState);
    for (const name of params.factoryNames ?? []) query.append("factoryNames", name);
    for (const tracker of params.trackers ?? []) query.append("trackers", tracker);
    return request<ImportCandidateList>(`/v1/admin/import-candidates?${query}`);
  },
  get: (candidateId: string) =>
    request<ImportCandidate>(
      `/v1/admin/import-candidates/${encodeURIComponent(candidateId)}`,
    ),
  exclude: (candidateId: string) =>
    request<void>(`/v1/admin/import-candidates/${encodeURIComponent(candidateId)}`, {
      method: "DELETE",
      headers: idempotencyHeaders(),
    }),
  confirm: (candidateId: string) =>
    request<{ orderId: string; requestId: string }>(
      `/v1/admin/import-candidates/${encodeURIComponent(candidateId)}/confirm`,
      { method: "POST", headers: idempotencyHeaders() },
    ),
  confirmBatch: (candidateIds: string[]) =>
    request<BatchConfirmResult>("/v1/admin/import-candidates/confirm", {
      method: "POST",
      headers: idempotencyHeaders(),
      body: JSON.stringify({ candidateIds }),
    }),
};
