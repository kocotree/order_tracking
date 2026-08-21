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
        <div class="sidebar-module">
          <span>产品资料</span>
          <RouterLink to="/products">产品列表</RouterLink>
        </div>
        <RouterLink to="/factories">工厂资料</RouterLink>
        <RouterLink to="/people/factory-applications">人员管理</RouterLink>
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
