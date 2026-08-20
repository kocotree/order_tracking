<template>
  <AdminShell>
    <section class="content-card people-card">
      <header class="content-header"><h1>管理员申请</h1></header>
      <PeopleTabs />
      <div class="people-toolbar">
        <label for="application-status">申请状态</label>
        <select id="application-status" v-model="statusFilter" @change="load">
          <option value="">全部状态</option>
          <option value="pending">待审核</option>
          <option value="approved">已通过</option>
          <option value="rejected">已拒绝</option>
        </select>
      </div>
      <p v-if="errorMessage" class="page-error">{{ errorMessage }}</p>
      <div class="people-table-scroll">
        <table class="people-table">
          <thead><tr><th>序号</th><th>申请人</th><th>手机号</th><th>申请时间</th><th>申请状态</th><th>操作</th></tr></thead>
          <tbody>
            <tr v-for="(application, index) in applications" :key="application.applicationId">
              <td>{{ index + 1 }}</td><td>{{ application.displayName }}</td><td>{{ application.phoneMasked }}</td>
              <td>{{ formatDate(application.submittedAt) }}</td>
              <td><span class="status-badge" :class="`is-${application.status}`">{{ statusLabel(application.status) }}</span></td>
              <td>
                <div v-if="application.status === 'pending'" class="people-row-actions">
                  <button class="text-button" type="button" @click="openDecision(application, 'approve')">通过</button>
                  <button class="text-button danger" type="button" @click="openDecision(application, 'reject')">拒绝</button>
                </div>
                <span v-else>—</span>
              </td>
            </tr>
            <tr v-if="!loading && applications.length === 0"><td colspan="6" class="empty-cell">暂无管理员申请</td></tr>
          </tbody>
        </table>
      </div>
    </section>
    <div v-if="decision" class="modal-backdrop" @click.self="decision = null">
      <form class="modal" @submit.prevent="confirmDecision">
        <header><h2>{{ decision.action === 'approve' ? '通过管理员申请' : '拒绝管理员申请' }}</h2><button type="button" aria-label="关闭" @click="decision = null">×</button></header>
        <div class="modal-body">
          <p v-if="decision.action === 'approve'">通过后，“{{ decision.application.displayName }}”将获得普通管理员角色。</p>
          <template v-else>
            <p>确认拒绝“{{ decision.application.displayName }}”的申请吗？拒绝记录将继续保留。</p>
            <label class="reject-field">拒绝原因<textarea v-model="rejectReason" maxlength="500" placeholder="请填写拒绝原因"></textarea></label>
          </template>
        </div>
        <footer><button type="button" class="secondary-button" @click="decision = null">取消</button><button class="primary-button" type="submit" :disabled="saving">确认</button></footer>
      </form>
    </div>
  </AdminShell>
</template>

<script setup lang="ts">
import { onMounted, ref } from "vue";

import { ApiError, identityApi, type AdminApplication } from "@/api/client";
import AdminShell from "@/components/AdminShell.vue";
import PeopleTabs from "@/components/PeopleTabs.vue";

const applications = ref<AdminApplication[]>([]);
const statusFilter = ref("");
const loading = ref(false);
const saving = ref(false);
const errorMessage = ref("");
const rejectReason = ref("");
const decision = ref<{ application: AdminApplication; action: "approve" | "reject" } | null>(null);

function statusLabel(status: string) {
  return { pending: "待审核", approved: "已通过", rejected: "已拒绝" }[status] ?? status;
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat("zh-CN", { dateStyle: "medium", timeStyle: "short", hour12: false }).format(new Date(value));
}

async function load() {
  loading.value = true;
  errorMessage.value = "";
  try {
    applications.value = (await identityApi.listApplications(statusFilter.value || undefined)).items;
  } catch (error) {
    errorMessage.value = error instanceof ApiError ? error.message : "管理员申请加载失败";
  } finally {
    loading.value = false;
  }
}

function openDecision(application: AdminApplication, action: "approve" | "reject") {
  rejectReason.value = "";
  decision.value = { application, action };
}

async function confirmDecision() {
  if (!decision.value) return;
  if (decision.value.action === "reject" && !rejectReason.value.trim()) {
    errorMessage.value = "请填写拒绝原因";
    return;
  }
  saving.value = true;
  try {
    const application = decision.value.application;
    if (decision.value.action === "approve") {
      await identityApi.approveApplication(application.applicationId, application.version);
    } else {
      await identityApi.rejectApplication(application.applicationId, application.version, rejectReason.value.trim());
    }
    decision.value = null;
    await load();
  } catch (error) {
    errorMessage.value = error instanceof ApiError ? error.message : "审核操作失败";
  } finally {
    saving.value = false;
  }
}

onMounted(load);
</script>
