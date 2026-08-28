import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { notificationApi } from "@/api/client";
import NotificationsPage from "@/pages/NotificationsPage.vue";

const push = vi.fn();
vi.mock("vue-router", async (importOriginal) => {
  const original = await importOriginal<typeof import("vue-router")>();
  return {
    ...original,
    useRoute: () => ({ query: { status: "unread", page: "2" } }),
    useRouter: () => ({ push }),
  };
});

beforeEach(() => {
  vi.restoreAllMocks();
  push.mockReset();
});

describe("administrator notifications", () => {
  it("keeps unread paging context when opening a target and marks the item read", async () => {
    vi.spyOn(notificationApi, "list").mockResolvedValue({
      items: [{
        notificationId: 11,
        category: "SHIPMENT",
        eventType: "shipment.submitted",
        targetType: "shipment",
        targetId: "shipment-1",
        title: "工厂已提交发货",
        summary: "发货单已形成正式记录",
        targetPath: "/shipments/shipment-1",
        readAt: null,
        createdAt: "2026-08-27T10:00:00",
      }],
      total: 11,
      page: 2,
      pageSize: 10,
      requestId: "request-1",
    });
    vi.spyOn(notificationApi, "markRead").mockResolvedValue(undefined);

    const wrapper = mount(NotificationsPage, {
      global: { stubs: { AdminShell: { template: "<div><slot /></div>" } } },
    });
    await flushPromises();
    expect(notificationApi.list).toHaveBeenCalledWith("unread", 2, 10);

    await wrapper.get(".notification-list-item").trigger("click");
    await flushPromises();
    expect(notificationApi.markRead).toHaveBeenCalledWith(11);
    expect(push).toHaveBeenCalledWith({
      path: "/shipments/shipment-1",
      query: { notificationReturnTo: "/notifications?status=unread&page=2" },
    });
  });
});
