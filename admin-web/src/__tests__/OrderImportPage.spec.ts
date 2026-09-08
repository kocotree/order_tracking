import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";

import { identityApi, orderImportApi, type ImportCandidate } from "@/api/client";
import OrderImportPage from "@/pages/OrderImportPage.vue";

const router = vi.hoisted(() => ({ replace: vi.fn().mockResolvedValue(undefined) }));

vi.mock("vue-router", () => ({
  useRoute: () => ({ query: {} }),
  useRouter: () => router,
}));

const candidate = {
  version: 1,
  candidateId: "candidate-1",
  orderNo: "E100",
  status: "PENDING",
  validationState: "READY",
  validationIssues: [],
  orderDate: "2026-08-22",
  tracker: "松子",
  contractShipDates: ["2026-08-30"], contractShipDate: "2026-08-30",
  category: "帽子",
  totalQuantity: 100,
  shippedQuantity: 0,
  pendingQuantity: 100,
  importedOrderId: null,
  lines: [{ candidateLineId: 1, contractShipDate: "2026-08-30", sourceContractShipDate: "2026-09-03", sourceSkuId: "6970000000001", productName: "测试童帽", propertiesValue: "蓝色 / 120", category: "童帽春夏", factoryName: "测试工厂", orderQuantity: 100, shippedQuantity: 0, pendingQuantity: 100, validationIssues: [] }],
  updatedAt: "2026-08-22T09:00:00",
} satisfies ImportCandidate;

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: Error) => void;
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}

afterEach(() => {
  vi.restoreAllMocks();
  router.replace.mockClear();
});

describe("pending order import page", () => {
  it("shows confirmed filters and only selects ready pending candidates", async () => {
    vi.spyOn(orderImportApi, "latestRun").mockResolvedValue(null);
    const list = vi.spyOn(orderImportApi, "list").mockResolvedValue({ items: [candidate, { ...candidate, candidateId: "candidate-2", orderNo: "E101", validationState: "INVALID", validationIssues: ["FACTORY_NOT_MATCHED"] }], total: 2, page: 1, pageSize: 10, requestId: "request" });
    const wrapper = mount(OrderImportPage, { global: { stubs: { AdminShell: { template: "<div><slot /></div>" }, RouterLink: { template: "<a><slot /></a>" } } } });
    await flushPromises();

    expect(wrapper.text()).toContain("待导入订单");
    expect(wrapper.text()).toContain("获取飞书新订单");
    expect(wrapper.text()).toContain("每页展示 10 条待导入订单");
    expect(wrapper.findAll("tbody input[type=checkbox]")[0].attributes("disabled")).toBeUndefined();
    expect(wrapper.findAll("tbody input[type=checkbox]")[1].attributes("disabled")).toBeDefined();

    await wrapper.get(".import-category-filter").setValue("帽子");
    await wrapper.get(".import-search-form").trigger("submit");
    await flushPromises();
    expect(list).toHaveBeenLastCalledWith(expect.objectContaining({ category: "帽子" }));
  });
});

it("returns to the last valid page after the result count shrinks and updates the URL", async () => {
  vi.spyOn(orderImportApi, "latestRun").mockResolvedValue(null);
  const list = vi.spyOn(orderImportApi, "list").mockResolvedValue({ items: [candidate], total: 200, page: 1, pageSize: 10, requestId: "test" });
  const wrapper = mount(OrderImportPage, { global: { stubs: { AdminShell: { template: "<div><slot/></div>" }, RouterLink: { template: "<a><slot/></a>" } } } });
  await flushPromises();
  list.mockResolvedValueOnce({ items: [], total: 11, page: 20, pageSize: 10, requestId: "test" }).mockResolvedValue({ items: [candidate], total: 11, page: 2, pageSize: 10, requestId: "test" });
  await wrapper.get("button[aria-label='第 20 页']").trigger("click");
  await flushPromises();
  expect(list).toHaveBeenLastCalledWith(expect.objectContaining({ page: 2 }));
  expect(router.replace).toHaveBeenLastCalledWith(expect.objectContaining({ query: expect.objectContaining({ page: "2" }) }));
  expect(wrapper.get("tbody .import-sequence-column").text()).toBe("11");
  wrapper.unmount();
});

it("renders candidates while both auxiliary requests are pending, and survives their failures", async () => {
  const factories = deferred<Awaited<ReturnType<typeof identityApi.listFactories>>>();
  const latest = deferred<Awaited<ReturnType<typeof orderImportApi.latestRun>>>();
  vi.spyOn(identityApi, "listFactories").mockReturnValue(factories.promise);
  const latestRequest = vi.spyOn(orderImportApi, "latestRun").mockReturnValue(latest.promise);
  const list = vi.spyOn(orderImportApi, "list").mockResolvedValue({ items: [candidate], total: 1, page: 1, pageSize: 10, requestId: "test" });
  const wrapper = mount(OrderImportPage, { global: { stubs: { AdminShell: { template: "<div><slot/></div>" }, RouterLink: { template: "<a><slot/></a>" } } } });
  try {
    await flushPromises();
    expect(latestRequest).toHaveBeenCalledTimes(1);
    expect(wrapper.text()).toContain("E100");
    expect(wrapper.text()).not.toContain("正在加载候选订单");
    factories.reject(new Error("factories unavailable"));
    latest.reject(new Error("history unavailable"));
    await flushPromises();
    expect(wrapper.text()).toContain("E100");
    expect(list).toHaveBeenCalledTimes(1);
  } finally {
    factories.resolve({ items: [], total: 0 });
    latest.resolve(null);
    await flushPromises();
    wrapper.unmount();
  }
});

const mountPage = () => mount(OrderImportPage, { global: { stubs: { AdminShell: { template: "<div><slot/></div>" }, RouterLink: { template: "<a><slot/></a>" } } } });
const listResponse = (orderNo: string) => ({ items: [{ ...candidate, orderNo }], total: 1, page: 1, pageSize: 10, requestId: "test" });
const running = { runId: "run-1", status: "RUNNING", startedAt: "2026-09-08T00:00:00", finishedAt: null, pagesRead: 0, recordsRead: 0, candidatesCreated: 0, candidatesUpdated: 0, skippedRecords: 0, failedRecords: 0, errorCode: null, requestId: "test" };

it("keeps the latest search result when the initial candidate response arrives late", async () => {
  vi.spyOn(identityApi, "listFactories").mockResolvedValue({ items: [], total: 0 });
  vi.spyOn(orderImportApi, "latestRun").mockResolvedValue(null);
  const initial = deferred<Awaited<ReturnType<typeof orderImportApi.list>>>();
  const list = vi.spyOn(orderImportApi, "list").mockReturnValueOnce(initial.promise).mockResolvedValue(listResponse("NEW"));
  const wrapper = mountPage();
  await wrapper.get("input[type=search]").setValue("NEW");
  await wrapper.get("form").trigger("submit");
  await flushPromises();
  expect(wrapper.text()).toContain("NEW");
  initial.resolve(listResponse("OLD"));
  await flushPromises();
  expect(wrapper.text()).not.toContain("OLD");
  expect(wrapper.text()).toContain("NEW");
  expect(list).toHaveBeenCalledTimes(2);
  wrapper.unmount();
});

it("resumes an active run and refreshes candidates once on completion", async () => {
  vi.useFakeTimers();
  vi.spyOn(identityApi, "listFactories").mockResolvedValue({ items: [], total: 0 });
  vi.spyOn(orderImportApi, "latestRun").mockResolvedValue(running);
  const getRun = vi.spyOn(orderImportApi, "getRun").mockResolvedValue({ ...running, status: "SUCCEEDED", finishedAt: "2026-09-08T00:01:00", candidatesCreated: 1 });
  const list = vi.spyOn(orderImportApi, "list").mockResolvedValue(listResponse("FIRST"));
  const wrapper = mountPage();
  try {
    await flushPromises();
    expect(list).toHaveBeenCalledTimes(1);
    expect(wrapper.text()).toContain("正在获取");
    await vi.advanceTimersByTimeAsync(1200);
    expect(getRun).toHaveBeenCalledTimes(1);
    expect(list).toHaveBeenCalledTimes(2);
    expect(wrapper.text()).toContain("获取完成：新增 1 个");
    await vi.advanceTimersByTimeAsync(2400);
    expect(getRun).toHaveBeenCalledTimes(1);
  } finally { wrapper.unmount(); vi.useRealTimers(); }
});

it("ignores late run history after a manual fetch has started", async () => {
  vi.useFakeTimers();
  const history = deferred<Awaited<ReturnType<typeof orderImportApi.latestRun>>>();
  vi.spyOn(identityApi, "listFactories").mockResolvedValue({ items: [], total: 0 });
  vi.spyOn(orderImportApi, "latestRun").mockReturnValue(history.promise);
  vi.spyOn(orderImportApi, "createRun").mockResolvedValue(running);
  const getRun = vi.spyOn(orderImportApi, "getRun").mockResolvedValue(running);
  vi.spyOn(orderImportApi, "list").mockResolvedValue(listResponse("FIRST"));
  const wrapper = mountPage();
  try {
    await flushPromises();
    await wrapper.get(".pending-import-fetch-button").trigger("click");
    await flushPromises();
    history.resolve({ ...running, runId: "older-run" });
    await flushPromises();
    await vi.advanceTimersByTimeAsync(1200);
    expect(getRun).toHaveBeenCalledTimes(1);
    expect(getRun).toHaveBeenCalledWith("run-1");
  } finally { wrapper.unmount(); vi.useRealTimers(); }
});

it("does not start polling when run history returns after leaving the page", async () => {
  vi.useFakeTimers();
  const history = deferred<Awaited<ReturnType<typeof orderImportApi.latestRun>>>();
  vi.spyOn(identityApi, "listFactories").mockResolvedValue({ items: [], total: 0 });
  vi.spyOn(orderImportApi, "latestRun").mockReturnValue(history.promise);
  const getRun = vi.spyOn(orderImportApi, "getRun");
  vi.spyOn(orderImportApi, "list").mockResolvedValue(listResponse("FIRST"));
  const wrapper = mountPage();
  wrapper.unmount();
  try {
    history.resolve(running);
    await flushPromises();
    await vi.advanceTimersByTimeAsync(2400);
    expect(getRun).not.toHaveBeenCalled();
  } finally { vi.useRealTimers(); }
});

it("does not refresh candidates when an in-flight poll completes after leaving", async () => {
  vi.useFakeTimers();
  const response = deferred<Awaited<ReturnType<typeof orderImportApi.getRun>>>();
  vi.spyOn(identityApi, "listFactories").mockResolvedValue({ items: [], total: 0 });
  vi.spyOn(orderImportApi, "latestRun").mockResolvedValue(running);
  const getRun = vi.spyOn(orderImportApi, "getRun").mockReturnValue(response.promise);
  const list = vi.spyOn(orderImportApi, "list").mockResolvedValue(listResponse("FIRST"));
  const wrapper = mountPage();
  try {
    await flushPromises();
    vi.advanceTimersByTime(1200);
    expect(getRun).toHaveBeenCalledTimes(1);
    wrapper.unmount();
    response.resolve({ ...running, status: "SUCCEEDED" });
    await flushPromises();
    await vi.advanceTimersByTimeAsync(2400);
    expect(getRun).toHaveBeenCalledTimes(1);
    expect(list).toHaveBeenCalledTimes(1);
  } finally { wrapper.unmount(); vi.useRealTimers(); }
});
