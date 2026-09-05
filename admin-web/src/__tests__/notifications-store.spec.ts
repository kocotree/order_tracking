import { createPinia, setActivePinia } from "pinia";
import { beforeEach, expect, it, vi } from "vitest";
import { notificationApi, type NotificationItem } from "@/api/client";
import { useNotificationsStore } from "@/stores/notifications";
beforeEach(() => { vi.restoreAllMocks(); setActivePinia(createPinia()); });
const item = () => ({ notificationId: 1, readAt: null, title: "发货" }) as NotificationItem;
it("removes a read notification from shared summaries and decrements once", async () => {
  vi.spyOn(notificationApi, "list").mockResolvedValue({ items: [item()] } as never);
  vi.spyOn(notificationApi, "unreadCount").mockResolvedValue({ count: 2 } as never);
  const read = vi.spyOn(notificationApi, "markRead").mockResolvedValue(undefined);
  const store = useNotificationsStore(); await store.refresh();
  await Promise.all([store.markRead(item()), store.markRead(item())]);
  expect(read).toHaveBeenCalledTimes(1); expect(store.recent).toEqual([]); expect(store.unreadCount).toBe(1);
});
it("keeps unread state when marking fails", async () => {
  vi.spyOn(notificationApi, "markRead").mockRejectedValue(new Error("offline"));
  const store = useNotificationsStore(); store.recent = [item()]; store.unreadCount = 1;
  await expect(store.markRead(item())).rejects.toThrow("offline");
  expect(store.recent).toHaveLength(1); expect(store.unreadCount).toBe(1);
});
it("does not restore read state from an older refresh response", async () => {
  let resolve!: (value: never) => void;
  vi.spyOn(notificationApi, "list").mockImplementation(() => new Promise((done) => { resolve = done; }));
  vi.spyOn(notificationApi, "unreadCount").mockResolvedValue({ count: 1 } as never);
  vi.spyOn(notificationApi, "markRead").mockResolvedValue(undefined);
  const store = useNotificationsStore(); const refresh = store.refresh();
  await store.markRead(item()); resolve({ items: [item()] } as never); await refresh;
  expect(store.recent).toEqual([]); expect(store.unreadCount).toBe(0);
});

it("clears cached notifications when the authenticated user changes", async () => {
  const store = useNotificationsStore(); store.setUser("first");
  store.recent = [item()]; store.unreadCount = 1;
  store.setUser("second");
  expect(store.recent).toEqual([]); expect(store.unreadCount).toBe(0);
});
