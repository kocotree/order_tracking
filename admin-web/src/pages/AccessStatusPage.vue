<template>
  <AuthFrame modifier="auth-page--status">
    <div class="auth-card auth-card--status is-disabled">
      <span class="auth-status-icon" aria-hidden="true">!</span>
      <div class="auth-card__heading auth-card__heading--status">
        <p class="auth-eyebrow">无法进入系统</p>
        <h1>当前账号已停用</h1>
        <p>该飞书账号暂无访问权限，请联系最高管理员处理。</p>
      </div>
      <dl class="auth-status-detail">
        <div><dt>飞书用户</dt><dd>{{ identity.currentUser?.displayName }}</dd></div>
        <div><dt>账号状态</dt><dd>已停用</dd></div>
      </dl>
    </div>
  </AuthFrame>
</template>

<script setup lang="ts">
import AuthFrame from "@/components/AuthFrame.vue";
import { useIdentityStore } from "@/stores";

const identity = useIdentityStore();
</script>
