import { defineStore } from "pinia";
import { ref } from "vue";
import { notificationApi, type NotificationItem } from "@/api/client";

export const useNotificationsStore = defineStore("notifications", () => {
  const recent = ref<NotificationItem[]>([]);
  const unreadCount = ref(0);
  const revision = ref(0);
  const readIds = new Set<number>();
  let loading: Promise<void> | undefined;
  let owner: string | undefined;
  function setUser(userId: string | undefined) {
    if (owner === userId) return;
    owner = userId;
    recent.value = []; unreadCount.value = 0; readIds.clear(); pending.clear();
    revision.value++; loading = undefined;
  }
  const pending = new Map<number, Promise<void>>();

  async function refresh() {
    if (loading) return loading;
    const version = revision.value;
    const request = Promise.all([notificationApi.list("unread", 1, 3), notificationApi.unreadCount()])
      .then(([list, count]) => {
        // A response started before a read must never restore its unread state.
        if (version !== revision.value) return;
        recent.value = list.items.filter((item) => !item.readAt && !readIds.has(item.notificationId));
        unreadCount.value = count.count;
      }).finally(() => { if (loading === request) loading = undefined; });
    loading = request;
    return request;
  }

  async function markRead(item: NotificationItem) {
    if (item.readAt || readIds.has(item.notificationId)) return;
    const existing = pending.get(item.notificationId);
    if (existing) return existing;
    const user = owner;
    const operation = notificationApi.markRead(item.notificationId).then(() => {
      if (user !== owner) return;
      readIds.add(item.notificationId);
      item.readAt = new Date().toISOString();
      recent.value = recent.value.filter((entry) => entry.notificationId !== item.notificationId);
      unreadCount.value = Math.max(0, unreadCount.value - 1);
      revision.value++;
    }).finally(() => { pending.delete(item.notificationId); });
    pending.set(item.notificationId, operation);
    return operation;
  }
  return { recent, unreadCount, revision, refresh, markRead, setUser };
});
