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
              <select v-model="category" @change="search"><option value="">全部分类</option><option v-for="value in productCategories" :key="value" :value="value">{{ value }}</option></select>
            </label>

            <div class="order-multiselect">
              <button class="order-multiselect-trigger" type="button" :aria-expanded="factoryOpen" @click="toggleFactoryMenu">
                <span>{{ factoryLabel }}</span><svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="m7 9 5 5 5-5" /></svg>
              </button>
              <div v-if="factoryOpen" class="order-multiselect-menu is-open">
                <strong>选择工厂（可多选）</strong><input v-model="factorySearch" class="order-multiselect-search" type="search" aria-label="搜索工厂名称" placeholder="搜索工厂名称" autocomplete="off" @keydown.enter.prevent />
                <label v-for="item in filteredFactories" :key="item.factoryId" class="order-multiselect-option">
                  <input v-model="factoryIds" type="checkbox" :value="item.factoryId" @change="search" /><span>{{ item.factoryName }}</span>
                </label>
                <span v-if="filteredFactories.length === 0" class="order-multiselect-empty">{{ factorySearch ? "没有匹配的工厂" : "暂无工厂" }}</span>
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

            <label class="order-select-field">
              <span class="sr-only">派工状态</span>
              <select v-model="dispatchStatus" aria-label="派工状态" @change="search"><option value="all">全部派工状态</option><option value="全部派工">全部派工</option><option value="部分派工">部分派工</option><option value="未派工">未派工</option></select>
            </label>
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
                <template v-for="column in sortableColumns" :key="column.key">
                  <th v-if="column.key === 'status'" scope="col">派工状态</th>
                  <th scope="col">
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
                </template>
                <th scope="col">操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(item, index) in items" :key="item.orderId">
                <td class="order-sequence-cell">{{ (page - 1) * pageSize + index + 1 }}</td>
                <td><RouterLink class="row-link" :to="detailRoute(item.orderId)">{{ item.orderNo }}</RouterLink></td>
                <td class="order-product-summary"><strong>{{ productSummary(item) }}</strong></td>
                <td class="category-summary" :title="displayCategories(item).join('、')">
                  <span v-for="value in displayCategories(item)" :key="value" class="category-tag">{{ value }}</span>
                  <span v-if="displayCategories(item).length === 0">—</span>
                </td>
                <td class="tracker-cell"><span class="tracker-tags"><span v-for="tracker in item.trackers" :key="tracker" class="tracker-tag" :data-tracker="tracker">{{ tracker }}</span><span v-if="!item.trackers.length">—</span></span></td>
                <td>{{ factorySummary(item) }}</td>
                <td class="date-summary" :title="item.contractShipDates.join('、')">{{ item.contractShipDates.join("、") || "—" }}</td>
                <td><div class="list-progress-line"><span class="progress-track"><span class="progress-bar" :style="{ width: `${Math.min(item.progressPercent ?? 0, 100)}%` }"></span></span><span class="list-progress-percent">{{ item.progressPercent == null ? "—" : `${item.progressPercent}%` }}</span></div></td>
                <td class="order-shipment-count">{{ number(item.shippedQuantity) }} / {{ number(item.totalQuantity) }}</td>
                <td class="order-dispatch-status">{{ item.dispatchStatus }}</td>
                <td><span class="status-badge" :class="statusTone(item)">{{ item.displayStatus }}</span></td>
                <td><div class="order-row-actions"><RouterLink class="order-view-button" :to="detailRoute(item.orderId)">详情</RouterLink><button v-if="item.lifecycle === 'DRAFT'" class="order-delete-button" type="button" @click="deleteTarget = item">删除</button></div></td>
              </tr>
              <tr v-if="items.length === 0"><td colspan="12"><div class="empty-state"><strong>没有符合当前条件的订单</strong><p>可以调整搜索词、状态或筛选条件后重新查询。</p></div></td></tr>
            </tbody>
          </table>
        </div>
        <footer class="order-list-footer">
          <span>每页展示 10 条订单。</span>
          <NumberPagination :page="page" :total="total" :loading="loading" @change="go" />
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
import { productCategories, sortedCategories } from "@/productCategories";
import { useRoute, useRouter } from "vue-router";
import { computed, onBeforeUnmount, onMounted, ref } from "vue";

import { ApiError, identityApi, orderApi, type Factory, type Order } from "@/api/client";
import NumberPagination from "@/components/NumberPagination.vue";
import AdminShell from "@/components/AdminShell.vue";

type TableSortKey = "orderNo" | "productName" | "category" | "tracker" | "factory" | "contractShipDate" | "progressPercent" | "shippedQuantity" | "status";

const statuses = [{ label: "全部", value: "all" }, { label: "未完成", value: "未完成" }, { label: "已逾期", value: "已逾期" }, { label: "已完成", value: "已完成" }, { label: "草稿", value: "草稿" }];
const sortableColumns: { key: TableSortKey; label: string }[] = [
  { key: "orderNo", label: "订单编号" }, { key: "productName", label: "产品名称" }, { key: "category", label: "分类" },
  { key: "tracker", label: "跟单人员" }, { key: "factory", label: "工厂" }, { key: "contractShipDate", label: "合同出货时间" },
  { key: "progressPercent", label: "发货进度" }, { key: "shippedQuantity", label: "已发/订单数" }, { key: "status", label: "状态" },
];
const trackers = ["烧麦", "松子", "橄榄", "大葱", "青椒"];
const route = useRoute();
const router = useRouter();
const queryValue = (key: string) => { const value = route?.query[key]; return Array.isArray(value) ? value[0] ?? "" : value ?? ""; };
const queryValues = (key: string) => { const value = route?.query[key]; return Array.isArray(value) ? value.filter((item): item is string => Boolean(item)) : value ? [value] : []; };
const initialPage = Number.parseInt(queryValue("page"), 10);
const initialSort = queryValue("sortBy");
const initialTableSort = initialSort.match(/^(orderNo|productName|category|tracker|factory|contractShipDate|progressPercent|shippedQuantity|status)(Asc|Desc)$/);
const items = ref<Order[]>([]);
const factories = ref<Pick<Factory, "factoryId" | "factoryName" | "supplierNumber">[]>([]);
const total = ref(0);
const page = ref(Number.isInteger(initialPage) && initialPage > 0 ? initialPage : 1);
const pageSize = 10;
const keyword = ref(queryValue("keyword"));
const status = ref(statuses.some((item) => item.value === route?.query.status) ? String(route.query.status) : "all");
const category = ref(queryValue("category"));
const factoryIds = ref<string[]>(queryValues("factoryId"));
const selectedTrackers = ref<string[]>(queryValues("tracker"));
const dispatchStatus = ref(["全部派工", "部分派工", "未派工"].includes(queryValue("dispatchStatus")) ? queryValue("dispatchStatus") : "all");
const sortBy = ref(initialTableSort ? initialSort : "priority");
const tableSortKey = ref<TableSortKey | null>(initialTableSort?.[1] as TableSortKey | undefined ?? null);
const tableSortDirection = ref<"asc" | "desc">(initialTableSort?.[2] === "Desc" ? "desc" : "asc");
const loading = ref(true);
const errorMessage = ref("");
const factoryOpen = ref(false);
const trackerOpen = ref(false);
const deleteTarget = ref<Order | null>(null);

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / pageSize)));
const factoryLabel = computed(() => factoryIds.value.length === 0 ? "全部工厂" : factoryIds.value.length === 1 ? factories.value.find((item) => item.factoryId === factoryIds.value[0])?.factoryName ?? "已选 1 个工厂" : `已选 ${factoryIds.value.length} 个工厂`);
const trackerLabel = computed(() => selectedTrackers.value.length === 0 ? "全部跟单人员" : selectedTrackers.value.length === 1 ? selectedTrackers.value[0] : `已选 ${selectedTrackers.value.length} 位跟单人员`);
const number = (value: number | null) => value == null ? "—" : value.toLocaleString("zh-CN");
const productSummary = (order: Order) => [...new Set((order.detailMode ? order.details : order.lines).map((line) => line.productName).filter(Boolean))].join("、") || "—";
const factorySummary = (order: Order) => [...new Set((order.detailMode ? order.details : order.factoryProgress).map((row) => row.factoryName))].join("、") || "—";

function displayCategories(order: Order) {
  return sortedCategories((order.detailMode ? order.details : order.lines).map((line) => line.category));
}

function statusTone(order: Order) {
  if (order.lifecycle === "DRAFT" || order.displayStatus === "草稿") return "is-draft";
  if (order.displayStatus === "已逾期") return "is-danger";
  if (order.displayStatus === "已完成") return "is-success";
  return "is-info";
}

function listQuery() {
  const query: Record<string, string | string[]> = {};
  if (keyword.value.trim()) query.keyword = keyword.value.trim();
  if (status.value !== "all") query.status = status.value;
  if (category.value) query.category = category.value;
  if (factoryIds.value.length) query.factoryId = factoryIds.value;
  if (selectedTrackers.value.length) query.tracker = selectedTrackers.value;
  if (dispatchStatus.value !== "all") query.dispatchStatus = dispatchStatus.value;
  if (sortBy.value !== "priority") query.sortBy = sortBy.value;
  if (page.value !== 1) query.page = String(page.value);
  return query;
}
const detailRoute = (orderId: string) => ({ path: `/orders/${orderId}`, query: listQuery() });

let requestSequence = 0;
async function load() { const requestId = ++requestSequence;
  loading.value = true;
  errorMessage.value = "";
  try {
    const result = await orderApi.list({ keyword: keyword.value, status: status.value, dispatchStatus: dispatchStatus.value, category: category.value || undefined, factoryIds: factoryIds.value, trackers: selectedTrackers.value, sortBy: sortBy.value, includeDrafts: true, page: page.value, pageSize });
    if (requestId !== requestSequence) return;
    const lastPage = Math.max(1, Math.ceil(result.total / pageSize));
    if (page.value > lastPage) { page.value = lastPage; await router?.replace({ path: "/orders", query: listQuery() }); await load(); return; }
    items.value = result.items;
    total.value = result.total;
  } catch (error) {
    if (requestId === requestSequence) errorMessage.value = error instanceof ApiError ? error.message : "订单列表加载失败";
  } finally {
    if (requestId === requestSequence) loading.value = false;
  }
}

async function syncAndLoad() { await router?.replace({ path: "/orders", query: listQuery() }); await load(); }
async function search() { page.value = 1; await syncAndLoad(); }
async function setStatus(value: string) { status.value = value; await search(); }
async function go(value: number) { if (value < 1 || value > totalPages.value || value === page.value) return; page.value = value; await syncAndLoad(); }

async function toggleSort(key: TableSortKey) {
  if (tableSortKey.value === key) tableSortDirection.value = tableSortDirection.value === "asc" ? "desc" : "asc";
  else { tableSortKey.value = key; tableSortDirection.value = "asc"; }
  sortBy.value = `${key}${tableSortDirection.value === "asc" ? "Asc" : "Desc"}`;
  await search();
}

async function reset() {
  factorySearch.value = "";
  keyword.value = ""; status.value = "all"; dispatchStatus.value = "all"; category.value = ""; factoryIds.value = []; selectedTrackers.value = [];
  sortBy.value = "priority"; tableSortKey.value = null; tableSortDirection.value = "asc";
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
  void identityApi.listFactoryOptions().then((result) => { factories.value = result.items; }).catch(() => undefined);
  await load();
});
onBeforeUnmount(() => { requestSequence += 1; document.removeEventListener("click", closeMenus); });

const factorySearch = ref("");
const filteredFactories = computed(() => factories.value.filter((item) => item.factoryName.includes(factorySearch.value.trim())));
</script>
