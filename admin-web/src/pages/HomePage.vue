<template>
  <AdminShell>
    <article class="dashboard-page">
      <section class="dashboard-search-panel" aria-label="订单快速搜索">
        <form class="dashboard-search-form" role="search" @submit.prevent="applySearch">
          <label class="dashboard-search-field">
            <span class="sr-only">搜索订单编号或产品名称</span>
            <svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><circle cx="11" cy="11" r="6.5" /><path d="m16 16 4 4" /></svg>
            <input v-model="keyword" type="search" placeholder="输入订单编号或产品名称" autocomplete="off" />
            <button v-if="keyword" class="dashboard-search-clear" type="button" aria-label="清除搜索" @click="clearSearch">×</button>
          </label>
          <button class="dashboard-search-submit" type="submit">搜索</button>
        </form>
      </section>

      <div v-if="appliedKeyword" class="dashboard-search-summary" role="status">
        “{{ appliedKeyword }}”找到 {{ displayedOrders.length }} 个订单。
      </div>

      <div class="dashboard-overview">
        <section class="dashboard-stat-grid" aria-label="订单统计">
          <RouterLink class="dashboard-stat-card" to="/orders/import"><span>待导入订单</span><strong>{{ dashboard?.pendingImportOrders ?? 0 }}</strong></RouterLink>
          <RouterLink class="dashboard-stat-card" :to="{ path: '/shipments', query: { dateFrom: shanghaiToday(), dateTo: shanghaiToday() } }"><span>今日发货记录</span><strong>{{ dashboard?.todayShipments ?? 0 }}</strong></RouterLink>
          <RouterLink class="dashboard-stat-card" :to="{ path: '/orders', query: { status: '已逾期' } }"><span>逾期订单</span><strong>{{ dashboard?.overdueOrders ?? 0 }}</strong></RouterLink>
        </section>

        <section class="section-card dashboard-notification-card" aria-labelledby="dashboard-notifications-title">
          <header class="dashboard-section-header">
            <h2 id="dashboard-notifications-title">最近通知</h2>
            <RouterLink class="dashboard-text-button" to="/notifications">全部通知</RouterLink>
          </header>
          <div v-if="notifications.length" class="dashboard-notification-list">
            <button v-for="item in notifications" :key="item.notificationId" type="button" @click="openNotification(item)">
              <i v-if="!item.readAt" aria-hidden="true"></i><span><strong>{{ item.title }}</strong><small>{{ item.summary }}</small></span><time>{{ notificationTime(item.createdAt) }}</time>
            </button>
          </div>
          <div v-else class="dashboard-notification-empty"><strong>暂无通知</strong></div>
        </section>
      </div>

      <section class="section-card dashboard-orders-card" aria-labelledby="dashboard-orders-title">
        <header class="dashboard-section-header">
          <h2 id="dashboard-orders-title">订单</h2>
          <RouterLink class="dashboard-text-button" to="/orders">查看全部订单</RouterLink>
        </header>
        <p v-if="loading" class="page-state">正在加载订单…</p>
        <p v-else-if="errorMessage" class="page-error">{{ errorMessage }}</p>
        <div v-else class="table-scroll">
          <table class="dashboard-order-table data-grid-table">
            <thead>
              <tr>
                <th class="dashboard-sequence-column" scope="col">序号</th>
                <th v-for="column in sortableColumns" :key="column.key" scope="col">
                  <button
                    class="data-grid-sort-button"
                    :class="{ 'is-sorted': sortKey === column.key, 'is-sort-desc': sortKey === column.key && sortDirection === 'desc' }"
                    type="button"
                    @click="toggleSort(column.key)"
                  >
                    {{ column.label }}
                    <span class="data-grid-sort-arrows" aria-hidden="true"><span class="data-grid-sort-arrow is-up"></span><span class="data-grid-sort-arrow is-down"></span></span>
                  </button>
                </th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(item, index) in displayedOrders" :key="item.orderId">
                <td class="dashboard-sequence-cell">{{ index + 1 }}</td>
                <td><RouterLink class="dashboard-order-link" :to="`/orders/${item.orderId}`">{{ item.orderNo }}</RouterLink></td>
                <td class="dashboard-product-cell">{{ productSummary(item) }}</td>
                <td>
                  <span v-for="category in displayCategories(item)" :key="category" class="dashboard-category-tag" :data-category="category">{{ category }}</span>
                  <span v-if="displayCategories(item).length === 0">—</span>
                </td>
                <td><span class="dashboard-tracker-tag">{{ item.tracker }}</span></td>
                <td>{{ factorySummary(item) }}</td>
                <td>{{ item.contractShipDate }}</td>
                <td><div class="dashboard-progress-cell"><span><i :style="{ width: `${item.progressPercent}%` }"></i></span><em>{{ item.progressPercent }}%</em></div></td>
                <td>{{ number(item.shippedQuantity) }} / {{ number(item.totalQuantity) }}</td>
                <td><span class="order-status" :data-status="item.displayStatus">{{ item.displayStatus }}</span></td>
              </tr>
              <tr v-if="displayedOrders.length === 0">
                <td colspan="10"><div class="empty-state"><strong>没有匹配的订单</strong><p>搜索仅匹配订单编号和产品名称。</p></div></td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </article>
  </AdminShell>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";

import { ApiError, orderApi, type DashboardOrders, type NotificationItem, type Order } from "@/api/client";
import { useNotificationsStore } from "@/stores/notifications";
import AdminShell from "@/components/AdminShell.vue";

type SortKey = "orderNo" | "productName" | "category" | "tracker" | "factory" | "contractShipDate" | "progressPercent" | "quantity" | "status";

const sortableColumns: { key: SortKey; label: string }[] = [
  { key: "orderNo", label: "订单编号" },
  { key: "productName", label: "产品名称" },
  { key: "category", label: "分类" },
  { key: "tracker", label: "跟单人员" },
  { key: "factory", label: "工厂" },
  { key: "contractShipDate", label: "合同出货时间" },
  { key: "progressPercent", label: "发货进度" },
  { key: "quantity", label: "已发 / 订单数" },
  { key: "status", label: "状态" },
];

const dashboard = ref<DashboardOrders | null>(null);
const notificationStore = useNotificationsStore();
const notifications = computed(() => notificationStore.recent);
const route = useRoute(); const router = useRouter();
const loading = ref(true);
const errorMessage = ref("");
const keyword = ref("");
const appliedKeyword = ref("");
const sortKey = ref<SortKey | null>(null);
const sortDirection = ref<"asc" | "desc">("asc");

const number = (value: number) => value.toLocaleString("zh-CN");
const productSummary = (order: Order) => [...new Set(order.lines.map((item) => item.productName))].join("、") || "—";
const factorySummary = (order: Order) => [...new Set(order.factoryProgress.map((item) => item.factoryName))].join("、") || "—";

function displayCategories(order: Order) {
  const categories = new Set<"服装" | "帽子">();
  for (const line of order.lines) {
    if (!line.category) continue;
    categories.add(line.category === "童装春夏" || line.category === "童装秋冬" ? "服装" : "帽子");
  }
  return ["服装", "帽子"].filter((item): item is "服装" | "帽子" => categories.has(item as "服装" | "帽子"));
}

function sortValue(order: Order, key: SortKey): string | number {
  const values: Record<SortKey, string | number> = {
    orderNo: order.orderNo,
    productName: productSummary(order),
    category: displayCategories(order).join("、"),
    tracker: order.tracker,
    factory: factorySummary(order),
    contractShipDate: order.contractShipDate,
    progressPercent: order.progressPercent,
    quantity: order.shippedQuantity,
    status: order.displayStatus,
  };
  return values[key];
}

const displayedOrders = computed(() => {
  const normalizedKeyword = appliedKeyword.value.toLocaleLowerCase("zh-CN");
  const orders = [...(dashboard.value?.recentOrders ?? [])].filter((item) => {
    if (!normalizedKeyword) return true;
    return [item.orderNo, ...item.lines.map((line) => line.productName)].some((value) => value.toLocaleLowerCase("zh-CN").includes(normalizedKeyword));
  });
  if (!sortKey.value) return orders;
  const direction = sortDirection.value === "asc" ? 1 : -1;
  return orders.sort((left, right) => {
    const leftValue = sortValue(left, sortKey.value as SortKey);
    const rightValue = sortValue(right, sortKey.value as SortKey);
    if (typeof leftValue === "number" && typeof rightValue === "number") return (leftValue - rightValue) * direction;
    return String(leftValue).localeCompare(String(rightValue), "zh-CN", { numeric: true }) * direction;
  });
});

function applySearch() {
  appliedKeyword.value = keyword.value.trim();
}

function clearSearch() {
  keyword.value = "";
  appliedKeyword.value = "";
}

function toggleSort(key: SortKey) {
  if (sortKey.value === key) {
    sortDirection.value = sortDirection.value === "asc" ? "desc" : "asc";
    return;
  }
  sortKey.value = key;
  sortDirection.value = "asc";
}

function shanghaiToday() {
  const parts = new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit" }).formatToParts(new Date());
  return ["year", "month", "day"].map((type) => parts.find((part) => part.type === type)?.value).join("-");
}
const notificationTime = (value:string) => new Date(value).toLocaleString("zh-CN", { timeZone:"Asia/Shanghai", hour12:false });
async function openNotification(item:NotificationItem) {
  try { await notificationStore.markRead(item); }
  catch { errorMessage.value = "通知标记已读失败，请重试"; return; }
  await router.push({ path:item.targetPath, query:{ notificationReturnTo:route.fullPath } });
}

onMounted(async () => {
  try {
    const [dashboardResult] = await Promise.all([orderApi.dashboard(), notificationStore.refresh()]);
    dashboard.value = dashboardResult;

  } catch (error) {
    errorMessage.value = error instanceof ApiError ? error.message : "订单看板加载失败";
  } finally {
    loading.value = false;
  }
});
</script>
