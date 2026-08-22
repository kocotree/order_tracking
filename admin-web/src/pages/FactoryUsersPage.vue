<template>
  <AdminShell>
    <article class="people-management-page">
      <section class="section-card people-management-filter-card">
        <PeopleTabs />
        <div class="people-toolbar">
          <label class="people-user-filter" for="factory-user-filter"><span>所属工厂</span>
          <select id="factory-user-filter" v-model="factoryFilter">
            <option value="">全部工厂</option>
            <option v-for="factory in factories" :key="factory.factoryId" :value="factory.factoryId">{{ factory.factoryName }}</option>
          </select></label>
        </div>
      </section>
      <section class="section-card people-management-card">
        <header class="people-management-header"><h1>人员管理</h1></header>
        <p v-if="errorMessage" class="page-error">{{ errorMessage }}</p>
        <div class="people-table-scroll">
          <table class="people-table data-grid-table people-user-table">
          <thead><tr><th>序号</th><th><TableSortButton label="姓名" field="displayName" :sort-by="sortBy" :sort-order="sortOrder" @sort="sortField" /></th><th><TableSortButton label="角色" field="role" :sort-by="sortBy" :sort-order="sortOrder" @sort="sortField" /></th><th><TableSortButton label="职位" field="factoryPosition" :sort-by="sortBy" :sort-order="sortOrder" @sort="sortField" /></th><th><TableSortButton label="所属工厂" field="factoryName" :sort-by="sortBy" :sort-order="sortOrder" @sort="sortField" /></th><th><TableSortButton label="启用状态" field="isEnabled" :sort-by="sortBy" :sort-order="sortOrder" @sort="sortField" /></th><th>操作</th></tr></thead>
          <tbody>
            <tr v-for="(account, index) in filteredUsers" :key="account.userId">
              <td>{{ index + 1 }}</td><td>{{ account.displayName }}</td>
              <td>{{ account.role === 'factory' ? '工厂用户' : '管理员' }} <span v-if="account.isSuperAdmin" class="super-badge">最高权限</span></td>
              <td>{{ positionLabel(account.factoryPosition) }}</td><td>{{ factoryName(account.factoryId) }}</td>
              <td><span class="status-badge" :class="account.isEnabled ? 'is-approved' : 'is-disabled'">{{ account.isEnabled ? '已启用' : '已停用' }}</span></td>
              <td><button v-if="canToggle(account)" class="text-button" :class="{ danger: account.isEnabled }" type="button" @click="target = account">{{ account.isEnabled ? '停用' : '启用' }}</button><span v-else>—</span></td>
            </tr>
            <tr v-if="filteredUsers.length === 0"><td colspan="7" class="empty-cell">暂无用户</td></tr>
          </tbody>
          </table>
        </div>
      </section>
    </article>
    <div v-if="target" class="modal-backdrop" @click.self="target = null">
      <section class="modal" role="dialog" aria-modal="true">
        <header><h2>{{ target.isEnabled ? '停用用户' : '启用用户' }}</h2><button type="button" aria-label="关闭" @click="target = null">×</button></header>
        <div class="modal-body"><p>确认{{ target.isEnabled ? '停用' : '启用' }}“{{ target.displayName }}”吗？</p></div>
        <footer><button class="secondary-button" type="button" @click="target = null">取消</button><button class="primary-button" type="button" :disabled="saving" @click="confirmToggle">确认</button></footer>
      </section>
    </div>
  </AdminShell>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRoute } from "vue-router";

import { ApiError, identityApi, type Factory, type User } from "@/api/client";
import AdminShell from "@/components/AdminShell.vue";
import PeopleTabs from "@/components/PeopleTabs.vue";
import TableSortButton from "@/components/TableSortButton.vue";
import { useIdentityStore } from "@/stores";

type SortField = "displayName" | "role" | "factoryPosition" | "factoryName" | "isEnabled";

const identity = useIdentityStore();
const route = useRoute();
const users = ref<User[]>([]);
const factories = ref<Factory[]>([]);
const factoryFilter = ref("");
const errorMessage = ref("");
const target = ref<User | null>(null);
const saving = ref(false);
const sortBy = ref<SortField | "">("");
const sortOrder = ref<"asc" | "desc">("asc");
const filteredUsers = computed(() => {
  const rows = users.value.filter((item) => !factoryFilter.value || item.factoryId === factoryFilter.value);
  const field = sortBy.value;
  if (!field) return rows;
  const direction = sortOrder.value === "asc" ? 1 : -1;
  return [...rows].sort((left, right) => String(sortValue(left, field)).localeCompare(String(sortValue(right, field)), "zh-CN", { numeric: true }) * direction);
});

function positionLabel(position: string | null) {
  if (position === "owner") return "老板";
  if (position === "employee") return "工厂员工";
  return "—";
}

function factoryName(factoryId: string | null) {
  return factories.value.find((item) => item.factoryId === factoryId)?.factoryName ?? "—";
}

function sortValue(account: User, field: SortField) {
  if (field === "role") return account.role === "factory" ? "工厂用户" : "管理员";
  if (field === "factoryPosition") return positionLabel(account.factoryPosition);
  if (field === "factoryName") return factoryName(account.factoryId);
  if (field === "isEnabled") return account.isEnabled ? "已启用" : "已停用";
  return account.displayName;
}

function sortField(field: string) {
  const nextField = field as SortField;
  if (sortBy.value === nextField) sortOrder.value = sortOrder.value === "asc" ? "desc" : "asc";
  else { sortBy.value = nextField; sortOrder.value = "asc"; }
}

function canToggle(account: User) {
  return !account.isSuperAdmin && (account.role === "factory" || Boolean(identity.currentUser?.isSuperAdmin));
}

async function load() {
  errorMessage.value = "";
  try {
    const [factoryUsers, factoryList, adminUsers] = await Promise.all([
      identityApi.listFactoryUsers(),
      identityApi.listFactories(),
      identity.currentUser?.isSuperAdmin ? identityApi.listAdminUsers() : Promise.resolve({ items: [], total: 0 }),
    ]);
    factories.value = factoryList.items;
    users.value = [...adminUsers.items, ...factoryUsers.items];
  } catch (error) {
    errorMessage.value = error instanceof ApiError ? error.message : "用户列表加载失败";
  }
}

async function confirmToggle() {
  if (!target.value) return;
  saving.value = true;
  try {
    if (target.value.role === "factory") {
      await identityApi.setFactoryUserEnabled(target.value.userId, target.value.version, !target.value.isEnabled);
    } else {
      await identityApi.setAdminEnabled(target.value.userId, target.value.version, !target.value.isEnabled);
    }
    target.value = null;
    await load();
  } catch (error) {
    errorMessage.value = error instanceof ApiError ? error.message : "用户状态更新失败";
  } finally {
    saving.value = false;
  }
}

onMounted(async () => {
  if (typeof route.query.factory === "string") factoryFilter.value = route.query.factory;
  await load();
});
</script>
