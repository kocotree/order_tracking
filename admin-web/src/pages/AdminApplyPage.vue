<template>
  <AuthFrame modifier="auth-page--apply">
    <form class="auth-card auth-card--apply" novalidate @submit.prevent="submit">
      <div class="auth-card__heading auth-card__heading--compact"><h1>管理员申请</h1></div>
      <div class="auth-identity">
        <span class="auth-avatar">{{ identity.currentUser?.displayName.slice(0, 1) }}</span>
        <div><span>飞书用户</span><strong>{{ identity.currentUser?.displayName }}</strong></div>
        <span class="auth-identity__state">身份已识别</span>
      </div>
      <div class="auth-field">
        <label>飞书手机号</label>
        <div class="auth-readonly-value">{{ identity.currentUser?.phoneMasked || "未获取" }}</div>
      </div>
      <p class="auth-form-hint">
        {{ identity.currentUser?.phoneMasked ? "手机号由飞书企业身份提供，无需短信验证。" : "飞书未返回手机号，请重新登录或联系最高管理员检查应用权限。" }}
      </p>
      <p class="auth-form-message" :data-tone="messageTone" aria-live="polite">{{ message }}</p>
      <button class="auth-primary-button" type="submit" :disabled="submitting || !identity.currentUser?.phoneMasked">提交申请</button>
    </form>
  </AuthFrame>
</template>

<script setup lang="ts">
import { ref } from "vue";
import { useRouter } from "vue-router";

import { ApiError, identityApi } from "@/api/client";
import AuthFrame from "@/components/AuthFrame.vue";
import { useIdentityStore } from "@/stores";

const identity = useIdentityStore();
const router = useRouter();
const message = ref("");
const messageTone = ref("");
const submitting = ref(false);

function showError(error: unknown) {
  messageTone.value = "danger";
  message.value = error instanceof ApiError ? error.message : "操作失败，请稍后重试";
}

async function submit() {
  submitting.value = true;
  try {
    identity.ownApplication = await identityApi.submitApplication();
    await router.replace("/access-status/pending");
  } catch (error) {
    showError(error);
  } finally {
    submitting.value = false;
  }
}
</script>
