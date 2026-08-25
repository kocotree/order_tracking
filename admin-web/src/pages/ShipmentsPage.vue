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
            <label class="order-select-field shipment-factory-field"><span class="sr-only">选择工厂</span><select v-model="factoryName" @change="search"><option value="">全部工厂</option><option v-for="name in factories" :key="name" :value="name">{{ name }}</option></select></label>
            <label class="order-date-field"><span class="sr-only">发货开始日期</span><input v-model="dateFrom" type="date" @change="search" /></label><span class="order-date-separator">—</span><label class="order-date-field"><span class="sr-only">发货结束日期</span><input v-model="dateTo" type="date" @change="search" /></label>
            <button class="order-secondary-button" type="button" @click="reset">重置</button><button class="order-primary-button" type="submit">搜索</button>
          </div>
        </form>
      </section>
      <section class="section-card order-list-card" aria-labelledby="shipment-list-title">
        <header class="order-list-card-header"><div class="order-list-heading"><h1 id="shipment-list-title">发货单列表</h1></div></header>
        <p v-if="error" class="page-error">{{ error }}</p><p v-if="loading" class="page-state">正在加载发货单…</p>
        <div v-else class="table-scroll"><table class="orders-table shipment-list-table data-grid-table"><colgroup><col class="shipment-sequence-col" /><col class="shipment-number-col" /><col class="shipment-order-col" /><col class="shipment-factory-col" /><col class="shipment-product-col" /><col class="shipment-quantity-col" /><col class="shipment-date-col" /><col class="shipment-action-col" /></colgroup><thead><tr><th class="shipment-sequence-column" scope="col">序号</th><th v-for="column in columns" :key="column.key" scope="col"><TableSortButton :label="column.label" :field="column.key" :sort-by="sortKey || ''" :sort-order="sortDirection" @sort="toggleSort" /></th><th scope="col">操作</th></tr></thead><tbody>
          <tr v-for="(item, index) in pageItems" :key="item.shipmentId"><td class="shipment-sequence-cell">{{ (page - 1) * pageSize + index + 1 }}</td><td><RouterLink class="row-link" :to="`/shipments/${item.shipmentId}`">{{ item.shipmentNo }}</RouterLink></td><td class="shipment-order-cell">{{ orderNos(item) }}</td><td>{{ item.factoryName || item.factoryId }}</td><td class="shipment-product-summary" :title="productNames(item)">{{ productNames(item) }}</td><td class="shipment-number-cell">{{ number(item.totalQuantity) }}</td><td>{{ item.businessDate }}</td><td><RouterLink class="order-view-button" :to="`/shipments/${item.shipmentId}`">详情</RouterLink></td></tr>
          <tr v-if="!pageItems.length"><td colspan="8"><div class="empty-state"><div><span class="empty-state-mark">0</span><strong>没有符合当前条件的发货单</strong><p>可以调整搜索词、工厂或发货日期后重新查询。</p></div></div></td></tr>
        </tbody></table></div>
        <footer class="order-list-footer"><span>每页展示 10 条发货单。</span><nav class="order-pagination" aria-label="发货单分页"><span class="order-page-total">共 {{ filtered.length }} 条</span><button class="order-page-button order-page-arrow" type="button" aria-label="上一页" :disabled="page === 1" @click="page--">‹</button><button v-for="value in totalPages" :key="value" class="order-page-button" :class="{ 'is-current': page === value }" type="button" @click="page = value">{{ value }}</button><button class="order-page-button order-page-arrow" type="button" aria-label="下一页" :disabled="page === totalPages" @click="page++">›</button></nav></footer>
      </section>
    </article>
  </AdminShell>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { ApiError, shipmentApi, type Shipment } from "@/api/client";
import AdminShell from "@/components/AdminShell.vue";
import TableSortButton from "@/components/TableSortButton.vue";
type SortKey = "shipmentNo" | "orderNos" | "factory" | "productNames" | "totalQuantity" | "businessDate";
const columns: { key: SortKey; label: string }[] = [{ key: "shipmentNo", label: "发货单号" }, { key: "orderNos", label: "关联订单" }, { key: "factory", label: "工厂" }, { key: "productNames", label: "产品名称" }, { key: "totalQuantity", label: "发货数量" }, { key: "businessDate", label: "发货日期" }];
const items = ref<Shipment[]>([]); const keyword = ref(""); const factoryName = ref(""); const dateFrom = ref(""); const dateTo = ref(""); const loading = ref(true); const error = ref(""); const page = ref(1); const pageSize = 10; const sortKey = ref<SortKey | null>(null); const sortDirection = ref<"asc" | "desc">("asc");
const number = (value: number) => value.toLocaleString("zh-CN"); const orderNos = (item: Shipment) => [...new Set(item.lines.map((line) => line.orderNo))].join("、") || "—"; const productNames = (item: Shipment) => [...new Set(item.lines.map((line) => line.productName))].join("、") || "—";
const factories = computed(() => [...new Set(items.value.map((item) => item.factoryName || item.factoryId))].sort((a, b) => a.localeCompare(b, "zh-CN")));
function sortValue(item: Shipment, key: SortKey): string | number { if (key === "orderNos") return orderNos(item); if (key === "factory") return item.factoryName || item.factoryId; if (key === "productNames") return productNames(item); return item[key] ?? ""; }
const filtered = computed(() => { const value = keyword.value.trim().toLocaleLowerCase("zh-CN"); const result = items.value.filter((item) => (!value || [item.shipmentNo, orderNos(item)].join(" ").toLocaleLowerCase("zh-CN").includes(value)) && (!factoryName.value || (item.factoryName || item.factoryId) === factoryName.value) && (!dateFrom.value || (item.businessDate || "") >= dateFrom.value) && (!dateTo.value || (item.businessDate || "") <= dateTo.value)); if (!sortKey.value) return result.sort((a, b) => (b.businessDate || "").localeCompare(a.businessDate || "") || (b.shipmentNo || "").localeCompare(a.shipmentNo || "")); const key = sortKey.value; const direction = sortDirection.value === "asc" ? 1 : -1; return result.sort((a, b) => String(sortValue(a, key)).localeCompare(String(sortValue(b, key)), "zh-CN", { numeric: true }) * direction); });
const totalPages = computed(() => Math.max(1, Math.ceil(filtered.value.length / pageSize))); const pageItems = computed(() => filtered.value.slice((page.value - 1) * pageSize, page.value * pageSize));
function search() { page.value = 1; } function reset() { keyword.value = ""; factoryName.value = ""; dateFrom.value = ""; dateTo.value = ""; sortKey.value = null; sortDirection.value = "asc"; search(); } function toggleSort(field: string) { const key = field as SortKey; if (sortKey.value === key) sortDirection.value = sortDirection.value === "asc" ? "desc" : "asc"; else { sortKey.value = key; sortDirection.value = "asc"; } page.value = 1; }
onMounted(async () => { try { items.value = (await shipmentApi.list()).items; } catch (reason) { error.value = reason instanceof ApiError ? reason.message : "发货单加载失败"; } finally { loading.value = false; } });
</script>
