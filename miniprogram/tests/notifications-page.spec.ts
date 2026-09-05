import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ list: vi.fn() }));

vi.mock("../api/notifications", () => ({
  notificationApi: {
    list: mocks.list,
  },
}));

type NotificationPage = {
  data: {
    status: "all" | "unread";
    page: number;
    items: Array<{ categoryLabel: string; createdAtText: string }>;
    total: number;
    hasMore: boolean;
    loading: boolean;
  };
  setData(values: Partial<NotificationPage["data"]>): void;
  load(reset?: boolean): Promise<void>;
};

let page: NotificationPage;

beforeEach(async () => {
  vi.resetModules();
  mocks.list.mockReset();
  vi.stubGlobal("Page", (definition: NotificationPage) => {
    page = {
      ...definition,
      data: { ...definition.data, items: [] },
      setData(values) {
        Object.assign(this.data, values);
      },
    };
  });
  vi.stubGlobal("wx", { showToast: vi.fn() });
  await import("../pages/notifications/notifications");
});

describe("notification page presentation", () => {
  it("uses the shared Shanghai formatter without changing pagination", async () => {
    mocks.list.mockResolvedValue({
      items: [{
        notificationId: 1,
        category: "DUE_REMINDER",
        eventType: "due",
        targetType: "order",
        targetId: "order-1",
        title: "合同出货提醒",
        summary: "订单即将到达合同出货时间",
        targetPath: "/pages/admin-order-detail/admin-order-detail?orderId=order-1",
        readAt: null,
        createdAt: "2026-09-05T08:30:00.123456",
      }],
      total: 11,
      page: 1,
      pageSize: 10,
      requestId: "request-1",
    });

    await page.load(true);

    expect(page.data.items[0]).toMatchObject({
      categoryLabel: "合同出货",
      createdAtText: "2026-09-05 16:30",
    });
    expect(page.data.page).toBe(1);
    expect(page.data.hasMore).toBe(true);
  });
});
