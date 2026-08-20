<template>
  <AuthFrame modifier="auth-page--login">
    <div class="auth-card auth-card--login">
      <div class="auth-card__heading">
        <h1>登录跟单管理系统</h1>
        <p>使用公司飞书账号识别身份并进入系统</p>
      </div>
      <button class="auth-primary-button" type="button" @click="login">
        通过飞书登录
      </button>
    </div>
  </AuthFrame>
</template>

<script setup lang="ts">
import { useRoute } from "vue-router";

import { feishuLoginUrl } from "@/api/client";
import AuthFrame from "@/components/AuthFrame.vue";

const route = useRoute();

function login() {
  const returnTo = typeof route.query.returnTo === "string" ? route.query.returnTo : "/";
  window.location.assign(feishuLoginUrl(returnTo));
}
</script>
