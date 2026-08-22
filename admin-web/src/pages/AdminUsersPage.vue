<template>
  <AdminShell>
    <article class="people-management-page">
      <section class="section-card people-management-filter-card">
        <PeopleTabs />
      </section>
      <section class="section-card people-management-card">
        <header class="people-management-header"><h1>人员管理</h1></header>
        <p v-if="errorMessage" class="page-error">{{ errorMessage }}</p>
        <div class="people-table-scroll">
          <table class="people-table data-grid-table people-user-table">
          <thead><tr><th>序号</th><th><TableSortButton label="姓名" field="displayName" :sort-by="sortBy" :sort-order="sortOrder" @sort="sortField" /></th><th><TableSortButton label="角色" field="role" :sort-by="sortBy" :sort-order="sortOrder" @sort="sortField" /></th><th><TableSortButton label="手机号" field="phoneMasked" :sort-by="sortBy" :sort-order="sortOrder" @sort="sortField" /></th><th><TableSortButton label="启用状态" field="isEnabled" :sort-by="sortBy" :sort-order="sortOrder" @sort="sortField" /></th><th>操作</th></tr></thead>
          <tbody>
            <tr v-for="(user, index) in sortedUsers" :key="user.userId">
              <td>{{ index + 1 }}</td><td>{{ user.displayName }}</td>
              <td>管理员 <span v-if="user.isSuperAdmin" class="super-badge">最高权限</span></td>
              <td>{{ user.phoneMasked ?? '—' }}</td>
              <td><span class="status-badge" :class="user.isEnabled ? 'is-approved' : 'is-disabled'">{{ user.isEnabled ? '已启用' : '已停用' }}</span></td>
              <td><button v-if="!user.isSuperAdmin" class="text-button" :class="{ danger: user.isEnabled }" type="button" @click="target = user">{{ user.isEnabled ? '停用' : '启用' }}</button><span v-else>—</span></td>
            </tr>
            <tr v-if="users.length === 0"><td colspan="6" class="empty-cell">暂无管理员账号</td></tr>
          </tbody>
          </table>
        </div>
      </section>
    </article>
    <div v-if="target" class="modal-backdrop" @click.self="target = null">
      <section class="modal" role="dialog" aria-modal="true">
        <header><h2>{{ target.isEnabled ? '停用管理员' : '启用管理员' }}</h2><button type="button" aria-label="关闭" @click="target = null">×</button></header>
        <div class="modal-body"><p>确认{{ target.isEnabled ? '停用' : '启用' }}“{{ target.displayName }}”吗？</p></div>
        <footer><button class="secondary-button" type="button" @click="target = null">取消</button><button class="primary-button" type="button" :disabled="saving" @click="confirmToggle">确认</button></footer>
      </section>
    </div>
  </AdminShell>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from "vue";

import { ApiError, identityApi, type User } from "@/api/client";
import AdminShell from "@/components/AdminShell.vue";
import PeopleTabs from "@/components/PeopleTabs.vue";
import TableSortButton from "@/components/TableSortButton.vue";

type SortField = "displayName" | "role" | "phoneMasked" | "isEnabled";

const users = ref<User[]>([]);
const target = ref<User | null>(null);
const saving = ref(false);
const errorMessage = ref("");
const sortBy = ref<SortField | "">("");
const sortOrder = ref<"asc" | "desc">("asc");
const sortedUsers = computed(() => {
  const field = sortBy.value;
  if (!field) return users.value;
  const direction = sortOrder.value === "asc" ? 1 : -1;
  return [...users.value].sort((left, right) => String(sortValue(left, field)).localeCompare(String(sortValue(right, field)), "zh-CN", { numeric: true }) * direction);
});

function sortValue(user: User, field: SortField) {
  if (field === "role") return "管理员";
  if (field === "isEnabled") return user.isEnabled ? "已启用" : "已停用";
  return user[field] ?? "";
}

function sortField(field: string) {
  const nextField = field as SortField;
  if (sortBy.value === nextField) sortOrder.value = sortOrder.value === "asc" ? "desc" : "asc";
  else { sortBy.value = nextField; sortOrder.value = "asc"; }
}

async function load() {
  try {
    users.value = (await identityApi.listAdminUsers()).items;
  } catch (error) {
    errorMessage.value = error instanceof ApiError ? error.message : "管理员账号加载失败";
  }
}

async function confirmToggle() {
  if (!target.value) return;
  saving.value = true;
  try {
    await identityApi.setAdminEnabled(target.value.userId, target.value.version, !target.value.isEnabled);
    target.value = null;
    await load();
  } catch (error) {
    errorMessage.value = error instanceof ApiError ? error.message : "管理员状态更新失败";
  } finally {
    saving.value = false;
  }
}

onMounted(load);
</script>
