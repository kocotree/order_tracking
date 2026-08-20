<template>
  <nav class="people-tabs" aria-label="人员管理分类">
    <RouterLink v-if="identity.currentUser?.isSuperAdmin" to="/people/admin-applications">管理员申请</RouterLink>
    <RouterLink to="/people/factory-applications">工厂用户申请</RouterLink>
    <RouterLink to="/people/users">用户列表</RouterLink>
  </nav>
</template>

<script setup lang="ts">
import { useIdentityStore } from "@/stores";

const identity = useIdentityStore();
</script>
