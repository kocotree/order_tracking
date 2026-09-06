<template>
  <AdminShell>
    <article class="product-list-page">
      <section class="order-list-filter-card product-filter-card" aria-label="产品搜索">
        <form class="product-search-form" @submit.prevent="search">
          <label class="order-list-search-field product-search-field">
            <span class="sr-only">搜索产品资料</span>
            <svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><circle cx="11" cy="11" r="6.5" /><path d="m16 16 4 4" /></svg>
            <input v-model="keyword" type="search" placeholder="输入货号、产品编码、产品名称或颜色/规格" autocomplete="off" />
          </label>
          <button class="order-primary-button" type="submit">搜索</button>
        </form>
      </section>

      <section class="section-card product-list-card" aria-labelledby="product-list-title">
        <header class="order-list-card-header">
          <div class="order-list-heading"><h1 id="product-list-title">产品列表</h1></div>
        </header>
        <p v-if="errorMessage" class="page-error">{{ errorMessage }}</p>
        <div class="table-scroll">
          <table class="product-list-table data-grid-table">
            <thead>
              <tr>
                <th scope="col">序号</th>
                <th scope="col"><TableSortButton label="货号" field="iId" :sort-by="sortBy" :sort-order="sortOrder" @sort="sort($event as SortField)" /></th>
                <th scope="col">图片</th>
                <th scope="col"><TableSortButton label="产品编码" field="skuId" :sort-by="sortBy" :sort-order="sortOrder" @sort="sort($event as SortField)" /></th>
                <th scope="col"><TableSortButton label="产品名称" field="name" :sort-by="sortBy" :sort-order="sortOrder" @sort="sort($event as SortField)" /></th>
                <th scope="col"><TableSortButton label="颜色/规格" field="propertiesValue" :sort-by="sortBy" :sort-order="sortOrder" @sort="sort($event as SortField)" /></th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(item, index) in items" :key="item.variantId">
                <td class="product-sequence">{{ (page - 1) * pageSize + index + 1 }}</td>
                <td class="product-item-no">{{ item.iId }}</td>
                <td>
                  <ProductImage :src="item.imageUrl" :name="item.name" />
                </td>
                <td class="product-code-cell">{{ item.skuId }}</td>
                <td><strong class="product-name-cell">{{ item.name }}</strong></td>
                <td>{{ item.propertiesValue }}</td>
              </tr>
              <tr v-if="items.length === 0">
                <td colspan="6">
                  <div class="empty-state"><div><span class="empty-state-mark">0</span><strong>没有符合条件的产品</strong><p>可以更换货号、产品编码、产品名称或颜色/规格后重新搜索。</p></div></div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <footer class="order-list-footer">
          <span>每页展示 10 条产品资料。</span>
          <NumberPagination :page="page" :total="total" :loading="loading" @change="goTo" />
        </footer>
      </section>
    </article>
  </AdminShell>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from "vue";

import { ApiError, identityApi, type ProductListItem } from "@/api/client";
import NumberPagination from "@/components/NumberPagination.vue";
import AdminShell from "@/components/AdminShell.vue";
import ProductImage from "@/components/ProductImage.vue";
import TableSortButton from "@/components/TableSortButton.vue";

type SortField = "iId" | "skuId" | "name" | "propertiesValue";

const items = ref<ProductListItem[]>([]);
const keyword = ref("");
const page = ref(1);
const pageSize = 10;
const total = ref(0);
const sortBy = ref<SortField>("iId");
const sortOrder = ref<"asc" | "desc">("asc");
const errorMessage = ref("");
const loading = ref(false);
const totalPages = computed(() => Math.max(1, Math.ceil(total.value / pageSize)));

let requestSequence = 0;
async function load() { const requestId = ++requestSequence;
  loading.value = true; errorMessage.value = "";
  try {
    const result = await identityApi.listProducts({ keyword: keyword.value, page: page.value, pageSize, sortBy: sortBy.value, sortOrder: sortOrder.value });
    if (requestId !== requestSequence) return;
    const lastPage = Math.max(1, Math.ceil(result.total / pageSize));
    if (page.value > lastPage) { page.value = lastPage; await load(); return; }
    items.value = result.items;
    total.value = result.total;
  } catch (error) {
    if (requestId === requestSequence) errorMessage.value = error instanceof ApiError ? error.message : "产品资料加载失败";
  } finally { if (requestId === requestSequence) loading.value = false; }
}

async function search() {
  page.value = 1;
  await load();
}

async function sort(field: SortField) {
  if (sortBy.value === field) sortOrder.value = sortOrder.value === "asc" ? "desc" : "asc";
  else {
    sortBy.value = field;
    sortOrder.value = "asc";
  }
  page.value = 1;
  await load();
}

async function goTo(target: number) {
  if (target < 1 || target > totalPages.value) return;
  page.value = target;
  await load();
}

onMounted(load);
</script>
