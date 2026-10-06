import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, expect, it, vi } from "vitest";
import { identityApi, type FactoryApplication } from "@/api/client";
import FactoryApplicationsPage from "@/pages/FactoryApplicationsPage.vue";

afterEach(() => vi.restoreAllMocks());

it.each([
  ["2026-10-06T03:33:00", "2026-10-06T19:05:00"],
  ["2026-10-06T03:33:00Z", "2026-10-06T19:05:00Z"],
  ["2026-10-06T11:33:00+08:00", "2026-10-07T03:05:00+08:00"],
])("displays application and review timestamps in Shanghai time: %s", async (submittedAt, reviewedAt) => {
  const application: FactoryApplication = {
    applicationId: "a1", userId: "u1", realName: "测试用户", phoneMasked: "138****0000",
    position: "owner", requestedFactoryId: "f1", requestedFactoryName: "测试工厂",
    boundFactoryId: "f1", boundFactoryName: "测试工厂", factoryContacts: [],
    status: "approved", rejectionReason: null, reviewedBy: "admin", version: 1,
    submittedAt, reviewedAt,
  };
  vi.spyOn(identityApi, "listFactoryApplications").mockResolvedValue({ items: [application], total: 1 });
  const wrapper = mount(FactoryApplicationsPage, {
    global: { stubs: { AdminShell: { template: "<div><slot/></div>" }, PeopleTabs: true } },
  });
  await flushPromises();
  expect(wrapper.get("tbody tr").text()).toContain("2026年10月6日 11:33");
  await wrapper.get("tbody button").trigger("click");
  expect(wrapper.get(".detail-grid").text()).toContain("申请时间2026年10月6日 11:33");
  expect(wrapper.get(".detail-grid").text()).toContain("审核时间2026年10月7日 03:05");
  wrapper.unmount();
});
