<template>
  <AdminShell>
    <article class="people-management-page">
      <section class="section-card people-management-filter-card">
        <PeopleTabs />
        <div class="people-toolbar">
          <label class="people-user-filter" for="factory-application-status"><span>申请状态</span>
          <select id="factory-application-status" v-model="statusFilter" @change="load">
            <option value="">全部状态</option>
            <option value="pending">待审核</option>
            <option value="approved">已通过</option>
            <option value="rejected">已拒绝</option>
          </select></label>
        </div>
      </section>
      <section class="section-card people-management-card">
        <header class="people-management-header"><h1>人员管理</h1></header>
        <p v-if="errorMessage" class="page-error">{{ errorMessage }}</p>
        <div class="people-table-scroll">
          <table class="people-table data-grid-table people-factory-application-table">
          <thead><tr><th>序号</th><th>姓名</th><th>职位</th><th>申请工厂</th><th>申请时间</th><th>申请状态</th><th>操作</th></tr></thead>
          <tbody>
            <tr v-for="(application, index) in applications" :key="application.applicationId">
              <td>{{ index + 1 }}</td><td>{{ application.realName }}</td><td>{{ positionLabel(application.position) }}</td>
              <td>{{ application.requestedFactoryName }}</td><td>{{ formatDate(application.submittedAt) }}</td>
              <td><span class="status-badge" :class="`is-${application.status}`">{{ statusLabel(application.status) }}</span></td>
              <td><button class="text-button" type="button" @click="openDetail(application)">详情</button></td>
            </tr>
            <tr v-if="applications.length === 0"><td colspan="7" class="empty-cell">暂无工厂用户申请</td></tr>
          </tbody>
          </table>
        </div>
      </section>
    </article>

    <div v-if="selected" class="modal-backdrop" @click.self="closeDetail">
      <section class="modal application-detail" role="dialog" aria-modal="true">
        <header><h2>工厂用户申请详情</h2><button type="button" aria-label="关闭" @click="closeDetail">×</button></header>
        <div class="modal-body">
          <dl class="detail-grid">
            <div><dt>真实姓名</dt><dd>{{ selected.realName }}</dd></div>
            <div><dt>验证联系电话</dt><dd>{{ selected.phoneMasked }}</dd></div>
            <div><dt>职位</dt><dd>{{ positionLabel(selected.position) }}</dd></div>
            <div><dt>申请工厂</dt><dd>{{ selected.requestedFactoryName }}</dd></div>
            <div><dt>申请时间</dt><dd>{{ formatDate(selected.submittedAt) }}</dd></div>
            <div><dt>申请状态</dt><dd>{{ statusLabel(selected.status) }}</dd></div>
            <div v-if="selected.reviewedAt"><dt>审核时间</dt><dd>{{ formatDate(selected.reviewedAt) }}</dd></div>
            <div v-if="selected.rejectionReason"><dt>拒绝原因</dt><dd>{{ selected.rejectionReason }}</dd></div>
          </dl>
          <section class="contact-summary">
            <h3>工厂联系人</h3>
            <p v-for="contact in selected.factoryContacts" :key="`${contact.displayOrder}-${contact.phone}`">{{ contact.name }}　{{ contact.phone }}</p>
            <p v-if="selected.factoryContacts.length === 0">暂无联系人</p>
          </section>
          <label v-if="decision === 'approve'" class="decision-field">绑定工厂
            <select v-model="bindingFactoryId">
              <option v-for="factory in factories" :key="factory.factoryId" :value="factory.factoryId">{{ factory.supplierNumber }}　{{ factory.factoryName }}</option>
            </select>
          </label>
          <label v-if="decision === 'reject'" class="decision-field">拒绝原因
            <textarea v-model="rejectReason" maxlength="500" placeholder="请填写拒绝原因"></textarea>
          </label>
        </div>
        <footer>
          <template v-if="selected.status === 'pending' && !decision">
            <button class="secondary-button danger-outline" type="button" @click="decision = 'reject'">拒绝</button>
            <button class="primary-button" type="button" @click="startApprove">通过</button>
          </template>
          <template v-else-if="decision">
            <button class="secondary-button" type="button" @click="decision = null">返回</button>
            <button class="primary-button" type="button" :disabled="saving" @click="confirmDecision">确认</button>
          </template>
          <button v-else class="secondary-button" type="button" @click="closeDetail">关闭</button>
        </footer>
      </section>
    </div>
  </AdminShell>
</template>

<script setup lang="ts">
import { onMounted, ref } from "vue";

import { ApiError, identityApi, type Factory, type FactoryApplication } from "@/api/client";
import AdminShell from "@/components/AdminShell.vue";
import PeopleTabs from "@/components/PeopleTabs.vue";

const applications = ref<FactoryApplication[]>([]);
const factories = ref<Factory[]>([]);
const statusFilter = ref("");
const errorMessage = ref("");
const selected = ref<FactoryApplication | null>(null);
const decision = ref<"approve" | "reject" | null>(null);
const bindingFactoryId = ref("");
const rejectReason = ref("");
const saving = ref(false);

function positionLabel(position: string) {
  return position === "owner" ? "老板" : "工厂员工";
}

function statusLabel(status: string) {
  return { pending: "待审核", approved: "已通过", rejected: "已拒绝" }[status] ?? status;
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat("zh-CN", { dateStyle: "medium", timeStyle: "short", hour12: false }).format(new Date(value));
}

async function load() {
  errorMessage.value = "";
  try {
    applications.value = (await identityApi.listFactoryApplications(statusFilter.value || undefined)).items;
  } catch (error) {
    errorMessage.value = error instanceof ApiError ? error.message : "工厂用户申请加载失败";
  }
}

function openDetail(application: FactoryApplication) {
  selected.value = application;
  decision.value = null;
  rejectReason.value = "";
  bindingFactoryId.value = application.requestedFactoryId;
}

function closeDetail() {
  selected.value = null;
  decision.value = null;
}

async function startApprove() {
  decision.value = "approve";
  if (factories.value.length === 0) {
    try {
      factories.value = (await identityApi.listFactories()).items;
    } catch (error) {
      errorMessage.value = error instanceof ApiError ? error.message : "工厂列表加载失败";
    }
  }
}

async function confirmDecision() {
  if (!selected.value || !decision.value) return;
  if (decision.value === "approve" && !bindingFactoryId.value) {
    errorMessage.value = "请选择绑定工厂";
    return;
  }
  if (decision.value === "reject" && !rejectReason.value.trim()) {
    errorMessage.value = "请填写拒绝原因";
    return;
  }
  saving.value = true;
  try {
    if (decision.value === "approve") {
      await identityApi.approveFactoryApplication(selected.value.applicationId, selected.value.version, bindingFactoryId.value);
    } else {
      await identityApi.rejectFactoryApplication(selected.value.applicationId, selected.value.version, rejectReason.value.trim());
    }
    closeDetail();
    await load();
  } catch (error) {
    errorMessage.value = error instanceof ApiError ? error.message : "审核操作失败";
  } finally {
    saving.value = false;
  }
}

onMounted(load);
</script>
