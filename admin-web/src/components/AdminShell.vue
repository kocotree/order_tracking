<template>
  <div class="admin-shell">
    <header class="admin-topbar">
      <RouterLink class="admin-brand" to="/">跟单管理系统</RouterLink>
      <div class="admin-account">
        <span>{{ identity.currentUser?.displayName }}</span>
        <button type="button" @click="logout">退出登录</button>
      </div>
    </header>
    <div class="admin-layout">
      <aside class="admin-sidebar">
        <RouterLink to="/">首页</RouterLink>
        <template v-if="identity.currentUser?.isSuperAdmin">
          <RouterLink to="/people/admin-applications">管理员申请</RouterLink>
          <RouterLink to="/people/admin-users">管理员账号</RouterLink>
        </template>
      </aside>
      <main class="admin-main"><slot /></main>
    </div>
  </div>
</template>

<script setup lang="ts">
import { useRouter } from "vue-router";

import { useIdentityStore } from "@/stores";

const identity = useIdentityStore();
const router = useRouter();

async function logout() {
  await identity.logout();
  await router.replace("/login");
}
</script>
