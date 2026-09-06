<template>
  <nav class="people-tabs" aria-label="人员管理分类">
    <RouterLink v-if="identity.currentUser?.isSuperAdmin" to="/people/admin-users">管理员</RouterLink>
    <RouterLink to="/people/factory-applications">工厂用户申请</RouterLink>
    <RouterLink to="/people/users">工厂用户列表</RouterLink>
  </nav>
</template>

<script setup lang="ts">
import { useIdentityStore } from "@/stores";

const identity = useIdentityStore();
</script>
