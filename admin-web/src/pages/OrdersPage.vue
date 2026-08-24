<template>
  <AdminShell title="订单列表">
    <article class="order-list-page">
      <section class="order-list-filter-card" aria-label="订单筛选">
        <nav class="order-status-tabs" aria-label="订单状态">
          <button
            v-for="item in statuses"
            :key="item.value"
            class="order-status-tab"
            :class="{ 'is-active': status === item.value }"
            :aria-pressed="status === item.value"
            type="button"
            @click="setStatus(item.value)"
          >{{ item.label }}</button>
        </nav>

        <form class="order-filter-form" @submit.prevent="search">
          <div class="order-filter-row">
            <label class="order-list-search-field">
              <span class="sr-only">搜索订单编号、产品名称或颜色规格</span>
              <svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><circle cx="11" cy="11" r="6.5" /><path d="m16 16 4 4" /></svg>
              <input v-model="keyword" type="search" placeholder="输入订单编号、产品名称或颜色/规格" autocomplete="off" />
            </label>

            <label class="order-select-field">
              <span class="sr-only">选择分类</span>
              <select v-model="category" @change="search"><option value="">全部分类</option><option value="服装">服装</option><option value="帽子">帽子</option></select>
            </label>

            <div class="order-multiselect">
              <button class="order-multiselect-trigger" type="button" :aria-expanded="factoryOpen" @click="toggleFactoryMenu">
                <span>{{ factoryLabel }}</span><svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="m7 9 5 5 5-5" /></svg>
              </button>
              <div v-if="factoryOpen" class="order-multiselect-menu is-open">
                <strong>选择工厂（可多选）</strong>
                <label v-for="item in factories" :key="item.factoryId" class="order-multiselect-option">
                  <input v-model="factoryIds" type="checkbox" :value="item.factoryId" @change="search" /><span>{{ item.factoryName }}</span>
                </label>
                <span v-if="factories.length === 0" class="order-multiselect-empty">暂无工厂</span>
              </div>
            </div>

            <div class="order-multiselect order-tracker-multiselect">
              <button class="order-multiselect-trigger" type="button" :aria-expanded="trackerOpen" @click="toggleTrackerMenu">
                <span>{{ trackerLabel }}</span><svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="m7 9 5 5 5-5" /></svg>
              </button>
              <div v-if="trackerOpen" class="order-multiselect-menu is-open">
                <strong>选择跟单人员（可多选）</strong>
                <label v-for="item in trackers" :key="item" class="order-multiselect-option">
                  <input v-model="selectedTrackers" type="checkbox" :value="item" @change="search" /><span>{{ item }}</span>
                </label>
              </div>
            </div>

            <label class="order-date-field"><span class="sr-only">合同出货开始日期</span><input v-model="shipDateFrom" type="date" @change="search" /></label>
            <span class="order-date-separator">—</span>
            <label class="order-date-field"><span class="sr-only">合同出货结束日期</span><input v-model="shipDateTo" type="date" @change="search" /></label>
            <button class="order-secondary-button" type="button" @click="reset">重置</button>
            <button class="order-primary-button" type="submit">搜索</button>
          </div>
        </form>
      </section>

      <section class="section-card order-list-card" aria-labelledby="order-list-title">
        <header class="order-list-card-header"><h1 id="order-list-title">订单列表</h1></header>
        <p v-if="errorMessage" class="page-error">{{ errorMessage }}</p>
        <p v-if="loading" class="page-state">正在加载订单…</p>
        <div v-else class="table-scroll">
          <table class="orders-table order-list-table data-grid-table">
            <thead>
              <tr>
                <th class="order-sequence-column" scope="col">序号</th>
                <th v-for="column in sortableColumns" :key="column.key" scope="col">
                  <button
                    class="data-grid-sort-button"
                    :class="{ 'is-sorted': tableSortKey === column.key, 'is-sort-desc': tableSortKey === column.key && tableSortDirection === 'desc' }"
                    type="button"
                    @click="toggleSort(column.key)"
                  >
                    {{ column.label }}
                    <span class="data-grid-sort-arrows" aria-hidden="true"><span class="data-grid-sort-arrow is-up"></span><span class="data-grid-sort-arrow is-down"></span></span>
                  </button>
                </th>
                <th scope="col">操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(item, index) in items" :key="item.orderId">
                <td class="order-sequence-cell">{{ (page - 1) * pageSize + index + 1 }}</td>
                <td><RouterLink class="row-link" :to="`/orders/${item.orderId}`">{{ item.orderNo }}</RouterLink></td>
                <td class="order-product-summary"><strong>{{ productSummary(item) }}</strong></td>
                <td>
                  <span v-for="value in displayCategories(item)" :key="value" class="category-tag" :class="value === '帽子' ? 'is-hat' : 'is-clothing'">{{ value }}</span>
                  <span v-if="displayCategories(item).length === 0">—</span>
                </td>
                <td><span class="tracker-tag" :data-tracker="item.tracker">{{ item.tracker }}</span></td>
                <td>{{ factorySummary(item) }}</td>
                <td>{{ item.contractShipDate }}</td>
                <td><div class="list-progress-line"><span class="progress-track"><span class="progress-bar" :style="{ width: `${item.progressPercent}%` }"></span></span><span class="list-progress-percent">{{ item.progressPercent }}%</span></div></td>
                <td class="order-shipment-count">{{ number(item.shippedQuantity) }} / {{ number(item.totalQuantity) }}</td>
                <td><span class="status-badge" :class="statusTone(item)">{{ item.displayStatus }}</span></td>
                <td><div class="order-row-actions"><RouterLink class="order-view-button" :to="`/orders/${item.orderId}`">详情</RouterLink><button v-if="item.lifecycle === 'DRAFT'" class="order-delete-button" type="button" @click="deleteTarget = item">删除</button></div></td>
              </tr>
              <tr v-if="items.length === 0"><td colspan="11"><div class="empty-state"><strong>没有符合当前条件的订单</strong><p>可以调整搜索词、状态或筛选条件后重新查询。</p></div></td></tr>
            </tbody>
          </table>
        </div>
        <footer class="order-list-footer">
          <span class="order-page-total">共 {{ total }} 条</span>
          <nav class="order-pagination" aria-label="订单分页">
            <button class="order-page-button order-page-arrow" type="button" aria-label="上一页" :disabled="page <= 1" @click="go(page - 1)">‹</button>
            <button v-for="value in pageNumbers" :key="value" class="order-page-button" :class="{ 'is-current': page === value }" type="button" @click="go(value)">{{ value }}</button>
            <button class="order-page-button order-page-arrow" type="button" aria-label="下一页" :disabled="page >= totalPages" @click="go(page + 1)">›</button>
          </nav>
        </footer>
      </section>

      <div v-if="deleteTarget" class="modal-backdrop" @click.self="deleteTarget = null">
        <section class="modal action-modal" role="dialog" aria-modal="true" aria-labelledby="delete-order-title">
          <header><h2 id="delete-order-title">删除订单</h2></header>
          <div class="modal-body"><p>确认删除草稿订单 <strong>{{ deleteTarget.orderNo }}</strong>？删除后无法恢复。</p></div>
          <footer><button class="secondary-button" type="button" @click="deleteTarget = null">取消</button><button class="danger-button" type="button" @click="remove">确认删除</button></footer>
        </section>
      </div>
    </article>
  </AdminShell>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue";

import { ApiError, identityApi, orderApi, type Factory, type Order } from "@/api/client";
import AdminShell from "@/components/AdminShell.vue";

type TableSortKey = "orderNo" | "productName" | "category" | "tracker" | "factory" | "contractShipDate" | "progressPercent" | "shippedQuantity" | "status";

const statuses = [{ label: "全部", value: "all" }, { label: "未完成", value: "未完成" }, { label: "已逾期", value: "已逾期" }, { label: "已完成", value: "已完成" }, { label: "草稿", value: "草稿" }];
const sortableColumns: { key: TableSortKey; label: string }[] = [
  { key: "orderNo", label: "订单编号" }, { key: "productName", label: "产品名称" }, { key: "category", label: "分类" },
  { key: "tracker", label: "跟单人员" }, { key: "factory", label: "工厂" }, { key: "contractShipDate", label: "合同出货时间" },
  { key: "progressPercent", label: "发货进度" }, { key: "shippedQuantity", label: "已发/订单数" }, { key: "status", label: "状态" },
];
const trackers = ["烧麦", "松子", "橄榄", "大葱", "青椒"];
const items = ref<Order[]>([]);
const factories = ref<Factory[]>([]);
const total = ref(0);
const page = ref(1);
const pageSize = 10;
const keyword = ref("");
const status = ref("all");
const category = ref("");
const factoryIds = ref<string[]>([]);
const selectedTrackers = ref<string[]>([]);
const shipDateFrom = ref("");
const shipDateTo = ref("");
const sortBy = ref("priority");
const tableSortKey = ref<TableSortKey | null>(null);
const tableSortDirection = ref<"asc" | "desc">("asc");
const loading = ref(true);
const errorMessage = ref("");
const factoryOpen = ref(false);
const trackerOpen = ref(false);
const deleteTarget = ref<Order | null>(null);

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / pageSize)));
const pageNumbers = computed(() => Array.from({ length: totalPages.value }, (_, index) => index + 1));
const factoryLabel = computed(() => factoryIds.value.length === 0 ? "全部工厂" : factoryIds.value.length === 1 ? factories.value.find((item) => item.factoryId === factoryIds.value[0])?.factoryName ?? "已选 1 个工厂" : `已选 ${factoryIds.value.length} 个工厂`);
const trackerLabel = computed(() => selectedTrackers.value.length === 0 ? "全部跟单人员" : selectedTrackers.value.length === 1 ? selectedTrackers.value[0] : `已选 ${selectedTrackers.value.length} 位跟单人员`);
const number = (value: number) => value.toLocaleString("zh-CN");
const productSummary = (order: Order) => [...new Set(order.lines.map((line) => line.productName))].join("、") || "—";
const factorySummary = (order: Order) => [...new Set(order.factoryProgress.map((row) => row.factoryName))].join("、") || "—";

function displayCategories(order: Order) {
  const values = new Set<"服装" | "帽子">();
  for (const line of order.lines) {
    if (!line.category) continue;
    values.add(line.category === "童装春夏" || line.category === "童装秋冬" ? "服装" : "帽子");
  }
  return (["服装", "帽子"] as const).filter((value) => values.has(value));
}

function statusTone(order: Order) {
  if (order.lifecycle === "DRAFT" || order.displayStatus === "草稿") return "is-draft";
  if (order.displayStatus === "已逾期") return "is-danger";
  if (order.displayStatus === "已完成") return "is-success";
  return "is-info";
}

async function load() {
  loading.value = true;
  errorMessage.value = "";
  try {
    const result = await orderApi.list({ keyword: keyword.value, status: status.value, category: category.value || undefined, factoryIds: factoryIds.value, trackers: selectedTrackers.value, shipDateFrom: shipDateFrom.value || undefined, shipDateTo: shipDateTo.value || undefined, sortBy: sortBy.value, includeDrafts: true, page: page.value, pageSize });
    items.value = result.items;
    total.value = result.total;
  } catch (error) {
    errorMessage.value = error instanceof ApiError ? error.message : "订单列表加载失败";
  } finally {
    loading.value = false;
  }
}

async function search() { page.value = 1; await load(); }
async function setStatus(value: string) { status.value = value; await search(); }
async function go(value: number) { if (value < 1 || value > totalPages.value || value === page.value) return; page.value = value; await load(); }

async function toggleSort(key: TableSortKey) {
  if (tableSortKey.value === key) tableSortDirection.value = tableSortDirection.value === "asc" ? "desc" : "asc";
  else { tableSortKey.value = key; tableSortDirection.value = "asc"; }
  sortBy.value = `${key}${tableSortDirection.value === "asc" ? "Asc" : "Desc"}`;
  await search();
}

async function reset() {
  keyword.value = ""; status.value = "all"; category.value = ""; factoryIds.value = []; selectedTrackers.value = [];
  shipDateFrom.value = ""; shipDateTo.value = ""; sortBy.value = "priority"; tableSortKey.value = null; tableSortDirection.value = "asc";
  await search();
}

async function remove() {
  if (!deleteTarget.value) return;
  try { await orderApi.delete(deleteTarget.value.orderId); deleteTarget.value = null; await load(); }
  catch (error) { errorMessage.value = error instanceof ApiError ? error.message : "删除失败"; deleteTarget.value = null; }
}

function toggleFactoryMenu() { factoryOpen.value = !factoryOpen.value; trackerOpen.value = false; }
function toggleTrackerMenu() { trackerOpen.value = !trackerOpen.value; factoryOpen.value = false; }
function closeMenus(event: MouseEvent) { if (!(event.target as Element).closest(".order-multiselect")) { factoryOpen.value = false; trackerOpen.value = false; } }

onMounted(async () => {
  document.addEventListener("click", closeMenus);
  const result = await identityApi.listFactories().catch(() => null);
  factories.value = result?.items ?? [];
  await load();
});
onBeforeUnmount(() => document.removeEventListener("click", closeMenus));
</script>
