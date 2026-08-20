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
        <label for="apply-phone">手机号</label>
        <input id="apply-phone" v-model="phone" type="tel" inputmode="numeric" maxlength="11" autocomplete="tel" placeholder="请输入本人手机号" @input="digitsOnly('phone')" />
      </div>
      <div class="auth-field">
        <label for="apply-code">验证码</label>
        <div class="auth-code-row">
          <input id="apply-code" v-model="code" type="text" inputmode="numeric" maxlength="6" autocomplete="one-time-code" placeholder="请输入 6 位验证码" @input="digitsOnly('code')" />
          <button class="auth-secondary-button" type="button" :disabled="sending || countdown > 0" @click="sendCode">
            {{ countdown > 0 ? `${countdown}s 后重新获取` : "获取验证码" }}
          </button>
        </div>
      </div>
      <p class="auth-form-message" :data-tone="messageTone" aria-live="polite">{{ message }}</p>
      <button class="auth-primary-button" type="submit" :disabled="submitting">提交申请</button>
    </form>
  </AuthFrame>
</template>

<script setup lang="ts">
import { onUnmounted, ref } from "vue";
import { useRouter } from "vue-router";

import { ApiError, identityApi } from "@/api/client";
import AuthFrame from "@/components/AuthFrame.vue";
import { useIdentityStore } from "@/stores";

const identity = useIdentityStore();
const router = useRouter();
const phone = ref("");
const code = ref("");
const challengeId = ref("");
const message = ref("");
const messageTone = ref("");
const sending = ref(false);
const submitting = ref(false);
const countdown = ref(0);
let timer: number | undefined;

function digitsOnly(field: "phone" | "code") {
  if (field === "phone") phone.value = phone.value.replace(/\D/g, "");
  else code.value = code.value.replace(/\D/g, "");
  message.value = "";
}

function showError(error: unknown) {
  messageTone.value = "danger";
  message.value = error instanceof ApiError ? error.message : "操作失败，请稍后重试";
}

async function sendCode() {
  if (!/^1\d{10}$/.test(phone.value)) {
    messageTone.value = "danger";
    message.value = "请输入正确的 11 位手机号";
    return;
  }
  sending.value = true;
  try {
    const challenge = await identityApi.sendSms(phone.value);
    challengeId.value = challenge.challengeId;
    messageTone.value = "success";
    message.value = `验证码已发送至 ${challenge.phoneMasked}`;
    countdown.value = 60;
    timer = window.setInterval(() => {
      countdown.value -= 1;
      if (countdown.value <= 0 && timer) window.clearInterval(timer);
    }, 1000);
  } catch (error) {
    showError(error);
  } finally {
    sending.value = false;
  }
}

async function submit() {
  if (!challengeId.value) {
    messageTone.value = "danger";
    message.value = "请先获取验证码";
    return;
  }
  if (!/^\d{6}$/.test(code.value)) {
    messageTone.value = "danger";
    message.value = "请输入 6 位验证码";
    return;
  }
  submitting.value = true;
  try {
    identity.ownApplication = await identityApi.submitApplication(challengeId.value, code.value);
    await router.replace("/access-status/pending");
  } catch (error) {
    showError(error);
  } finally {
    submitting.value = false;
  }
}

onUnmounted(() => {
  if (timer) window.clearInterval(timer);
});
</script>
