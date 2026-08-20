<template>
  <AuthFrame modifier="auth-page--status">
    <div class="auth-card auth-card--status" :class="`is-${status}`">
      <span class="auth-status-icon" aria-hidden="true">{{ icon }}</span>
      <div class="auth-card__heading auth-card__heading--status">
        <p class="auth-eyebrow">{{ content.eyebrow }}</p>
        <h1>{{ content.title }}</h1>
        <p v-if="description">{{ description }}</p>
      </div>
      <dl class="auth-status-detail">
        <div><dt>飞书用户</dt><dd>{{ identity.currentUser?.displayName }}</dd></div>
        <div><dt>{{ content.detailLabel }}</dt><dd>{{ content.detailValue }}</dd></div>
      </dl>
      <button v-if="content.action" class="auth-primary-button" type="button" :disabled="refreshing" @click="act">
        {{ refreshing ? "正在刷新…" : content.action }}
      </button>
      <p class="auth-feedback" aria-live="polite">{{ feedback }}</p>
    </div>
  </AuthFrame>
</template>

<script setup lang="ts">
import { computed, ref } from "vue";
import { useRoute, useRouter } from "vue-router";

import AuthFrame from "@/components/AuthFrame.vue";
import { useIdentityStore } from "@/stores";

const route = useRoute();
const router = useRouter();
const identity = useIdentityStore();
const refreshing = ref(false);
const feedback = ref("");
const status = computed(() => String(route.params.status));
const meta = {
  pending: { icon: "◷", eyebrow: "申请已提交", title: "等待审核", detailLabel: "当前状态", detailValue: "待审核", action: "刷新审核状态" },
  rejected: { icon: "×", eyebrow: "申请未通过", title: "管理员申请已被拒绝", detailLabel: "审核结果", detailValue: "已拒绝", action: "重新申请" },
  disabled: { icon: "!", eyebrow: "无法进入系统", title: "当前账号已停用", detailLabel: "账号状态", detailValue: "已停用", action: "" },
} as const;
const content = computed(() => meta[status.value as keyof typeof meta] ?? meta.pending);
const icon = computed(() => content.value.icon);
const description = computed(() => {
  if (status.value === "rejected") return `拒绝原因：${identity.ownApplication?.rejectionReason ?? "请确认申请信息后重新提交。"}`;
  if (status.value === "disabled") return "该飞书账号暂无访问权限，请联系最高管理员处理。";
  return "";
});

async function act() {
  if (status.value === "rejected") {
    identity.ownApplication = null;
    await router.push({ path: "/admin-apply", query: { reapply: "1" } });
    return;
  }
  refreshing.value = true;
  const application = await identity.loadOwnApplication(true);
  if (application?.status === "approved") {
    await identity.loadCurrentUser(true);
    await router.replace("/");
  } else {
    feedback.value = "当前仍为待审核状态";
  }
  refreshing.value = false;
}
</script>
