<template>
  <AdminShell title="发货单列表">
    <article class="order-list-page shipment-list-page">
      <section class="order-list-filter-card" aria-label="发货单筛选">
        <form class="order-filter-form" @submit.prevent="search">
          <div class="order-filter-row shipment-filter-row">
            <label class="order-list-search-field">
              <span class="sr-only">搜索关联订单或发货单号</span>
              <svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><circle cx="11" cy="11" r="6.5" /><path d="m16 16 4 4" /></svg>
              <input v-model="keyword" type="search" placeholder="输入关联订单或发货单号" autocomplete="off" />
            </label>
            <div class="order-multiselect shipment-factory-field">
              <button class="order-multiselect-trigger" type="button" :aria-expanded="factoryOpen" @click="factoryOpen = !factoryOpen"><span>{{ factoryLabel }}</span><span>⌄</span></button>
              <div v-if="factoryOpen" class="order-multiselect-menu is-open"><strong>选择工厂（可多选）</strong><input v-model="factorySearch" class="order-multiselect-search" type="search" aria-label="搜索工厂名称" placeholder="搜索工厂名称" autocomplete="off" @keydown.enter.prevent />
                <label v-for="name in filteredFactories" :key="name" class="order-multiselect-option"><input v-model="factoryNames" type="checkbox" :value="name" /><span>{{ name }}</span></label>
                <span v-if="!filteredFactories.length" class="order-multiselect-empty">{{ factorySearch ? "没有匹配的工厂" : "暂无工厂" }}</span>
              </div>
            </div>
            <label class="order-date-field"><span class="sr-only">发货开始日期</span><input v-model="dateFrom" type="date" @change="search" /></label><span class="order-date-separator">—</span><label class="order-date-field"><span class="sr-only">发货结束日期</span><input v-model="dateTo" type="date" @change="search" /></label>
            <button class="order-secondary-button" type="button" @click="reset">重置</button><button class="order-primary-button" type="submit">搜索</button>
          </div>
        </form>
      </section>
      <section class="section-card order-list-card" aria-labelledby="shipment-list-title">
        <header class="order-list-card-header"><div class="order-list-heading"><h1 id="shipment-list-title">发货单列表</h1></div></header>
        <p v-if="error || optionsError" class="page-error">{{ error || optionsError }}</p><p v-if="loading" class="page-state">正在加载发货单…</p>
        <div v-else class="table-scroll"><table class="orders-table shipment-list-table data-grid-table"><colgroup><col class="shipment-sequence-col" /><col class="shipment-number-col" /><col class="shipment-order-col" /><col class="shipment-factory-col" /><col class="shipment-product-col" /><col class="shipment-quantity-col" /><col class="shipment-date-col" /><col class="shipment-action-col" /></colgroup><thead><tr><th class="shipment-sequence-column" scope="col">序号</th><th v-for="column in columns" :key="column.key" scope="col"><TableSortButton :label="column.label" :field="column.key" :sort-by="sortKey || ''" :sort-order="sortDirection" @sort="toggleSort" /></th><th scope="col">操作</th></tr></thead><tbody>
          <tr v-for="(item, index) in pageItems" :key="item.shipmentId"><td class="shipment-sequence-cell">{{ (page - 1) * pageSize + index + 1 }}</td><td><RouterLink class="row-link" :to="`/shipments/${item.shipmentId}`">{{ item.shipmentNo }}</RouterLink><span v-if="item.status === 'WITHDRAWN'"> · 已撤回</span></td><td class="shipment-order-cell">{{ item.orderNos }}</td><td>{{ item.factoryName || item.factoryId }}</td><td class="shipment-product-summary" :title="item.productNames">{{ item.productNames }}</td><td class="shipment-number-cell">{{ number(item.totalQuantity) }}</td><td>{{ item.businessDate }}</td><td><RouterLink class="order-view-button" :to="`/shipments/${item.shipmentId}`">详情</RouterLink></td></tr>
          <tr v-if="!pageItems.length"><td colspan="8"><div class="empty-state"><div><span class="empty-state-mark">0</span><strong>没有符合当前条件的发货单</strong><p>可以调整搜索词、工厂或发货日期后重新查询。</p></div></div></td></tr>
        </tbody></table></div>
        <footer class="order-list-footer"><span>每页展示 10 条发货单。</span><NumberPagination :page="page" :total="total" :loading="loading" @change="changePage" /></footer>
      </section>
    </article>
  </AdminShell>
</template>

<script setup lang="ts">
import { useRoute } from "vue-router";
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { ApiError, shipmentApi, type ShipmentSummary } from "@/api/client";
import NumberPagination from "@/components/NumberPagination.vue";
import AdminShell from "@/components/AdminShell.vue";
import TableSortButton from "@/components/TableSortButton.vue";
type SortKey = "shipmentNo" | "orderNos" | "factory" | "productNames" | "totalQuantity" | "businessDate";
const columns: { key: SortKey; label: string }[] = [{ key: "shipmentNo", label: "发货单号" }, { key: "orderNos", label: "关联订单" }, { key: "factory", label: "工厂" }, { key: "productNames", label: "产品名称" }, { key: "totalQuantity", label: "发货数量" }, { key: "businessDate", label: "发货日期" }];
const route = useRoute();
const queryDate = (value: unknown) => typeof value === "string" && /^\d{4}-\d{2}-\d{2}$/.test(value) && !Number.isNaN(Date.parse(value)) && new Date(value).toISOString().slice(0, 10) === value ? value : "";
const pageItems = ref<ShipmentSummary[]>([]); const total = ref(0); const factories = ref<string[]>([]);
const keyword = ref(""); const factoryNames = ref<string[]>([]); const factorySearch = ref(""); const factoryOpen = ref(false); const dateFrom = ref(queryDate(route?.query.dateFrom)); const dateTo = ref(queryDate(route?.query.dateTo)); const loading = ref(true); const error = ref(""); const optionsError = ref(""); const page = ref(1); const pageSize = 10; const sortKey = ref<SortKey | null>(null); const sortDirection = ref<"asc" | "desc">("asc");
const filteredFactories = computed(() => factories.value.filter(name => name.includes(factorySearch.value.trim())));
const factoryLabel = computed(() => factoryNames.value.length === 0 ? "全部工厂" : factoryNames.value.length === 1 ? factoryNames.value[0] : `已选 ${factoryNames.value.length} 个工厂`);
const number = (value: number) => value.toLocaleString("zh-CN");
let revision = 0;
let active = true;
async function load() {
  const requestRevision = ++revision;
  loading.value = true; error.value = "";
  try {
    const result = await shipmentApi.listSummary({ keyword: keyword.value.trim(), factories: [...factoryNames.value], dateFrom: dateFrom.value, dateTo: dateTo.value, sortBy: sortKey.value || "", sortOrder: sortDirection.value, page: page.value, pageSize });
    if (!active || requestRevision !== revision) return;
    total.value = result.total;
    const lastPage = Math.max(1, Math.ceil(result.total / pageSize));
    if (page.value > lastPage) { page.value = lastPage; void load(); return; }
    pageItems.value = result.items;
  } catch (reason) {
    if (active && requestRevision === revision) error.value = reason instanceof ApiError ? reason.message : "发货单加载失败";
  } finally {
    if (active && requestRevision === revision) loading.value = false;
  }
}
// Coalesce v-model watchers and their change/submit handlers into one request.
let scheduled = false;
function scheduleLoad() {
  if (scheduled) return;
  scheduled = true;
  queueMicrotask(() => { scheduled = false; if (active) void load(); });
}
function search() { page.value = 1; scheduleLoad(); }
function changePage(value: number) { page.value = value; scheduleLoad(); }
function reset() { keyword.value = ""; factoryNames.value = []; factorySearch.value = ""; dateFrom.value = ""; dateTo.value = ""; sortKey.value = null; sortDirection.value = "asc"; search(); }
function toggleSort(field: string) { const key = field as SortKey; if (sortKey.value === key) sortDirection.value = sortDirection.value === "asc" ? "desc" : "asc"; else { sortKey.value = key; sortDirection.value = "asc"; } search(); }
watch([keyword, factoryNames, dateFrom, dateTo], search, { flush: "sync", deep: true });
onMounted(() => {
  void load();
  void shipmentApi.listFactoryOptions().then(result => {
    if (active) factories.value = result.items.sort((a, b) => a.localeCompare(b, "zh-CN"));
  }).catch(() => { if (active) optionsError.value = "工厂筛选选项加载失败，请刷新重试"; });
});
onUnmounted(() => { active = false; revision++; });
</script>
