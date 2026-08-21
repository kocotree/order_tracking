<template>
  <AdminShell>
    <article class="order-workspace">
      <section class="order-filter-card">
        <form class="order-search-row" @submit.prevent="search">
          <label class="order-search-field"><span aria-hidden="true">⌕</span><input v-model="keyword" type="search" placeholder="搜索订单编号、产品名称或颜色/规格" /></label>
          <button class="order-primary-button" type="submit">搜索</button>
          <button class="order-secondary-button" type="button" @click="advancedOpen = !advancedOpen">高级筛选</button>
        </form>
        <div v-if="advancedOpen" class="advanced-filter-grid">
          <label>工厂<select v-model="factoryId"><option value="">全部工厂</option><option v-for="item in factories" :key="item.factoryId" :value="item.factoryId">{{ item.factoryName }}</option></select></label>
          <label>跟单人员<select v-model="tracker"><option value="">全部人员</option><option v-for="item in trackers" :key="item">{{ item }}</option></select></label>
          <label>合同出货时间起<input v-model="shipDateFrom" type="date" /></label>
          <label>合同出货时间止<input v-model="shipDateTo" type="date" /></label>
          <label>排序<select v-model="sortBy"><option value="priority">默认紧急程度</option><option value="shipDateAsc">合同出货时间升序</option><option value="shipDateDesc">合同出货时间降序</option><option value="orderDateDesc">订单日期最新</option><option value="updatedDesc">更新时间最新</option></select></label>
          <button class="order-primary-button filter-apply" type="button" @click="search">应用筛选</button>
        </div>
      </section>

      <section class="section-card order-list-card">
        <header class="order-list-header">
          <div><h1>订单列表</h1><p>草稿仅管理员网页端可见</p></div>
          <div class="more-menu-wrap">
            <button class="order-secondary-button" type="button" @click="moreOpen = !moreOpen">更多操作⌄</button>
            <RouterLink v-if="moreOpen" class="more-menu" to="/orders/new">手工新建订单</RouterLink>
          </div>
        </header>
        <nav class="status-tabs" aria-label="订单状态">
          <button v-for="item in statuses" :key="item.value" type="button" :class="{ 'is-active': status === item.value }" @click="setStatus(item.value)">{{ item.label }}</button>
        </nav>
        <p v-if="errorMessage" class="page-error">{{ errorMessage }}</p>
        <p v-if="loading" class="page-state">正在加载订单…</p>
        <div v-else class="table-scroll">
          <table class="order-table">
            <thead><tr><th>订单编号</th><th>产品名称</th><th>颜色/规格</th><th>工厂</th><th>跟单人员</th><th>合同出货时间</th><th>订单数量</th><th>已发数量</th><th>未发数量</th><th>发货进度</th><th>状态</th><th>操作</th></tr></thead>
            <tbody>
              <tr v-for="item in items" :key="item.orderId">
                <td><RouterLink class="order-link" :to="`/orders/${item.orderId}`">{{ item.orderNo }}</RouterLink></td>
                <td>{{ item.lines.map((line) => line.productName).join('、') }}</td>
                <td>{{ item.lines.map((line) => line.propertiesValue).join('、') }}</td>
                <td>{{ item.factoryProgress.map((row) => row.factoryName).join('、') || '—' }}</td>
                <td>{{ item.tracker }}</td><td>{{ item.contractShipDate }}</td>
                <td>{{ number(item.totalQuantity) }}</td><td>{{ number(item.shippedQuantity) }}</td><td>{{ number(item.pendingQuantity) }}</td>
                <td><div class="progress-cell"><span><i :style="{ width: `${item.progressPercent}%` }"></i></span><em>{{ item.progressPercent }}%</em></div></td>
                <td><span class="order-status" :data-status="item.displayStatus">{{ item.displayStatus }}</span></td>
                <td><div class="row-actions"><RouterLink :to="`/orders/${item.orderId}`">详情</RouterLink><RouterLink v-if="item.lifecycle === 'DRAFT'" :to="`/orders/${item.orderId}/edit`">编辑</RouterLink><button v-if="item.lifecycle === 'DRAFT'" type="button" @click="remove(item)">删除</button></div></td>
              </tr>
              <tr v-if="items.length === 0"><td colspan="12"><div class="empty-state"><strong>没有符合条件的订单</strong><p>可以更换状态、关键词或高级筛选条件。</p></div></td></tr>
            </tbody>
          </table>
        </div>
        <footer class="list-pagination"><span>共 {{ total }} 条</span><div><button :disabled="page <= 1" @click="go(page - 1)">‹</button><button class="is-current">{{ page }}</button><button :disabled="page >= totalPages" @click="go(page + 1)">›</button></div></footer>
      </section>
    </article>
  </AdminShell>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from "vue";

import { ApiError, identityApi, orderApi, type Factory, type Order } from "@/api/client";
import AdminShell from "@/components/AdminShell.vue";

const statuses = [{ label: "全部", value: "all" }, { label: "未完成", value: "未完成" }, { label: "已逾期", value: "已逾期" }, { label: "已完成", value: "已完成" }, { label: "草稿", value: "草稿" }];
const trackers = ["烧麦", "松子", "橄榄", "大葱", "青椒"];
const items = ref<Order[]>([]); const factories = ref<Factory[]>([]); const total = ref(0); const page = ref(1); const pageSize = 20;
const keyword = ref(""); const status = ref("all"); const factoryId = ref(""); const tracker = ref(""); const shipDateFrom = ref(""); const shipDateTo = ref(""); const sortBy = ref("priority");
const loading = ref(true); const errorMessage = ref(""); const advancedOpen = ref(false); const moreOpen = ref(false);
const totalPages = computed(() => Math.max(1, Math.ceil(total.value / pageSize)));
const number = (value: number) => value.toLocaleString("zh-CN");

async function load() {
  loading.value = true; errorMessage.value = "";
  try {
    const result = await orderApi.list({ keyword: keyword.value, status: status.value, factoryId: factoryId.value || undefined, trackers: tracker.value ? [tracker.value] : [], shipDateFrom: shipDateFrom.value || undefined, shipDateTo: shipDateTo.value || undefined, sortBy: sortBy.value, includeDrafts: true, page: page.value, pageSize });
    items.value = result.items; total.value = result.total;
  } catch (error) { errorMessage.value = error instanceof ApiError ? error.message : "订单列表加载失败"; }
  finally { loading.value = false; }
}
async function search() { page.value = 1; await load(); }
async function setStatus(value: string) { status.value = value; await search(); }
async function go(value: number) { if (value < 1 || value > totalPages.value) return; page.value = value; await load(); }
async function remove(item: Order) { if (!window.confirm(`确认删除草稿 ${item.orderNo}？`)) return; try { await orderApi.delete(item.orderId); await load(); } catch (error) { errorMessage.value = error instanceof ApiError ? error.message : "删除失败"; } }
onMounted(async () => { const result = await identityApi.listFactories().catch(() => null); factories.value = result?.items ?? []; await load(); });
</script>
