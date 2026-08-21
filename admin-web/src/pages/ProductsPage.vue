<template>
  <AdminShell>
    <section class="content-card product-card">
      <header class="content-header"><h1>产品列表</h1></header>
      <div class="people-toolbar product-toolbar">
        <input
          v-model="keyword"
          type="search"
          placeholder="输入货号、产品编码、产品名称或颜色/规格"
          @keyup.enter="search"
        />
        <button class="secondary-button" type="button" @click="search">搜索</button>
      </div>
      <p v-if="errorMessage" class="page-error">{{ errorMessage }}</p>
      <div class="people-table-scroll">
        <table class="people-table product-table">
          <thead>
            <tr>
              <th class="sequence-column">序号</th>
              <th><button class="sort-button" type="button" @click="sort('iId')">货号{{ sortMark('iId') }}</button></th>
              <th class="image-column">图片</th>
              <th><button class="sort-button" type="button" @click="sort('skuId')">产品编码{{ sortMark('skuId') }}</button></th>
              <th><button class="sort-button" type="button" @click="sort('name')">产品名称{{ sortMark('name') }}</button></th>
              <th><button class="sort-button" type="button" @click="sort('propertiesValue')">颜色/规格{{ sortMark('propertiesValue') }}</button></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(item, index) in items" :key="item.variantId">
              <td>{{ (page - 1) * pageSize + index + 1 }}</td>
              <td>{{ item.iId }}</td>
              <td><span class="product-image-placeholder">{{ item.imageAvailable ? '图片' : '无图' }}</span></td>
              <td>{{ item.skuId }}</td>
              <td><strong>{{ item.name }}</strong></td>
              <td>{{ item.propertiesValue }}</td>
            </tr>
            <tr v-if="items.length === 0"><td colspan="6" class="empty-cell">暂无产品资料</td></tr>
          </tbody>
        </table>
      </div>
      <footer class="product-pagination">
        <span>共 {{ total }} 条</span>
        <button class="secondary-button" type="button" :disabled="page <= 1" @click="goTo(page - 1)">上一页</button>
        <span>第 {{ page }} 页</span>
        <button class="secondary-button" type="button" :disabled="page >= totalPages" @click="goTo(page + 1)">下一页</button>
      </footer>
    </section>
  </AdminShell>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from "vue";

import { ApiError, identityApi, type ProductListItem } from "@/api/client";
import AdminShell from "@/components/AdminShell.vue";

type SortField = "iId" | "skuId" | "name" | "propertiesValue";

const items = ref<ProductListItem[]>([]);
const keyword = ref("");
const page = ref(1);
const pageSize = 10;
const total = ref(0);
const sortBy = ref<SortField>("iId");
const sortOrder = ref<"asc" | "desc">("asc");
const errorMessage = ref("");
const totalPages = computed(() => Math.max(1, Math.ceil(total.value / pageSize)));

async function load() {
  errorMessage.value = "";
  try {
    const result = await identityApi.listProducts({
      keyword: keyword.value,
      page: page.value,
      pageSize,
      sortBy: sortBy.value,
      sortOrder: sortOrder.value,
    });
    items.value = result.items;
    total.value = result.total;
  } catch (error) {
    errorMessage.value = error instanceof ApiError ? error.message : "产品资料加载失败";
  }
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

function sortMark(field: SortField) {
  if (sortBy.value !== field) return "";
  return sortOrder.value === "asc" ? " ↑" : " ↓";
}

async function goTo(target: number) {
  if (target < 1 || target > totalPages.value) return;
  page.value = target;
  await load();
}

onMounted(load);
</script>
