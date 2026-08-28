<template>
  <AdminShell title="通知记录">
    <article class="notifications-page">
      <section class="section-card notifications-card">
        <header class="notifications-header">
          <div class="notifications-title-row">
            <button class="notifications-back-button" type="button" @click="goBack" aria-label="返回上一页">
              <svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="m15 18-6-6 6-6" /></svg>
              <span>返回</span>
            </button>
            <h1>通知记录</h1>
          </div>
          <nav class="notification-tabs" aria-label="通知筛选">
            <button type="button" :class="{ 'is-active': status === 'all' }" @click="setStatus('all')">全部</button>
            <button type="button" :class="{ 'is-active': status === 'unread' }" @click="setStatus('unread')">未读</button>
          </nav>
        </header>
        <p v-if="loading" class="page-state">正在加载通知…</p>
        <p v-else-if="errorMessage" class="page-error">{{ errorMessage }}</p>
        <div v-else-if="items.length" class="notification-list">
          <button v-for="item in items" :key="item.notificationId" class="notification-list-item" type="button" @click="open(item)">
            <i v-if="!item.readAt" class="notification-unread-dot" aria-label="未读"></i>
            <span class="notification-category">{{ categoryLabel(item.category) }}</span>
            <span class="notification-copy"><strong>{{ item.title }}</strong><span>{{ item.summary }}</span></span>
            <time>{{ dateTime(item.createdAt) }}</time>
          </button>
        </div>
        <div v-else class="notification-empty">暂无通知</div>
        <footer v-if="totalPages > 1" class="notification-pagination">
          <button type="button" :disabled="page <= 1" @click="setPage(page - 1)">上一页</button>
          <span>{{ page }} / {{ totalPages }}</span>
          <button type="button" :disabled="page >= totalPages" @click="setPage(page + 1)">下一页</button>
        </footer>
      </section>
    </article>
  </AdminShell>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";

import { ApiError, notificationApi, type NotificationItem } from "@/api/client";
import AdminShell from "@/components/AdminShell.vue";

const route = useRoute();
const router = useRouter();
const status = ref<"all" | "unread">(route.query.status === "unread" ? "unread" : "all");
const page = ref(Math.max(Number(route.query.page) || 1, 1));
const items = ref<NotificationItem[]>([]);
const total = ref(0);
const loading = ref(true);
const errorMessage = ref("");
const totalPages = computed(() => Math.max(Math.ceil(total.value / 10), 1));

function goBack() {
  if (window.history.length > 1) return router.back();
  return router.push("/");
}

const categoryLabel = (value:string) => ({ NEW_ORDER:"新订单", DUE_REMINDER:"合同出货", SHIPMENT:"发货", REPAIR:"返修", BUSINESS_RESULT:"处理结果" }[value] ?? "业务通知");
const dateTime = (value:string) => new Date(value).toLocaleString("zh-CN", { timeZone:"Asia/Shanghai", hour12:false });

async function load() {
  loading.value = true; errorMessage.value = "";
  try { const result = await notificationApi.list(status.value, page.value, 10); items.value = result.items; total.value = result.total; }
  catch (error) { errorMessage.value = error instanceof ApiError ? error.message : "通知加载失败"; }
  finally { loading.value = false; }
}
async function syncRoute() { await router.push({ path:"/notifications", query:{ status:status.value, page:String(page.value) } }); await load(); }
async function setStatus(value:"all"|"unread") { status.value = value; page.value = 1; await syncRoute(); }
async function setPage(value:number) { page.value = value; await syncRoute(); }
async function open(item:NotificationItem) {
  if (!item.readAt) { await notificationApi.markRead(item.notificationId); item.readAt = new Date().toISOString(); }
  await router.push({ path:item.targetPath, query:{ notificationReturnTo:`/notifications?status=${status.value}&page=${page.value}` } });
}
onMounted(load);
</script>
