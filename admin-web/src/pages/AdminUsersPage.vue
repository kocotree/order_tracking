<template>
  <AdminShell>
    <section class="content-card people-card">
      <header class="content-header"><h1>管理员账号</h1></header>
      <p v-if="errorMessage" class="page-error">{{ errorMessage }}</p>
      <div class="people-table-scroll">
        <table class="people-table">
          <thead><tr><th>序号</th><th>姓名</th><th>角色</th><th>手机号</th><th>启用状态</th><th>操作</th></tr></thead>
          <tbody>
            <tr v-for="(user, index) in users" :key="user.userId">
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
import { onMounted, ref } from "vue";

import { ApiError, identityApi, type User } from "@/api/client";
import AdminShell from "@/components/AdminShell.vue";

const users = ref<User[]>([]);
const target = ref<User | null>(null);
const saving = ref(false);
const errorMessage = ref("");

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
