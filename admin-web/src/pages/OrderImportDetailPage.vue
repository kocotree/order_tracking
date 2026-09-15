<template>
  <AdminShell :title="candidate ? `待导入订单详情 · ${candidate.orderNo}` : '待导入订单详情'">
    <article v-if="candidate" class="order-detail-page pending-import-detail-page">
      <section class="section-card detail-overview-card">
        <header class="detail-page-header">
          <button class="detail-back-button" type="button" @click="backToList">
            <svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="m15 18-6-6 6-6" /></svg>
            <span>返回</span>
          </button>
          <div class="detail-title-row pending-import-detail-actions">
            <span class="status-badge" :class="candidate.status === 'IMPORTED' || candidate.validationState === 'READY' ? 'is-success' : 'is-warning'">
              {{ candidate.status === "IMPORTED" ? "已导入" : candidate.validationState === "READY" ? "可导入" : "资料待处理" }}
            </span>
            <button
              v-if="candidate.status === 'PENDING'"
              class="detail-primary-button"
              type="button"
              :disabled="saving || importing || dirty"
              :title="dirty ? '请先保存订单明细' : '确认导入当前候选为草稿，资料在派工时校验'"
              @click="openConfirm"
            >确认导入为草稿</button>
          </div>
        </header>
        <div class="detail-overview-content">
          <dl class="detail-summary-grid" aria-label="待导入订单概览">
            <div><dt>分类</dt><dd><span v-for="value in sortedCategories(candidate.lines.map((line) => line.category))" :key="value" class="category-tag">{{ value }}</span><span v-if="!candidate.lines.some((line) => line.category)">—</span></dd></div>
            <div><dt>跟单人员</dt><dd><span v-for="tracker in candidate.trackers" :key="tracker" class="tracker-tag" :data-tracker="tracker">{{ tracker }}</span><span v-if="!candidate.trackers.length">—</span></dd></div>
            <div><dt>合同出货时间</dt><dd class="detail-due-date">{{ candidate.contractShipDates.join("、") || "—" }}</dd></div>
            <div><dt>订单数量</dt><dd class="detail-summary-number">{{ number(candidate.totalQuantity) }}</dd></div>
            <div><dt>已发数量</dt><dd class="detail-summary-number">{{ number(candidate.shippedQuantity) }}</dd></div>
            <div><dt>未发数量</dt><dd class="detail-summary-number">{{ number(candidate.pendingQuantity) }}</dd></div>
          </dl>
          <p v-if="candidate.validationIssues.length" class="validation-callout">{{ issueText(candidate.validationIssues) }}</p>
        </div>
      </section>

      <section class="section-card detail-section-card">
        <header class="detail-section-header pending-import-detail-header">
          <div><h2>订单明细</h2><p v-if="candidate.status === 'PENDING'">可修改工厂、合同出货时间和已发数量</p></div>
          <div v-if="candidate.status === 'PENDING'" class="pending-import-save-actions">
            <span v-if="dirty">有未保存修改</span>
            <button class="detail-primary-button" type="button" :disabled="saving || importing || !dirty" @click="saveLines">
              {{ saving ? "保存中…" : "保存" }}
            </button>
          </div>
        </header>
        <div class="detail-table-scroll">
          <table class="detail-data-table product-detail-table pending-import-detail-table data-grid-table">
            <thead><tr><th class="detail-sequence-column">序号</th><th v-for="column in lineColumns" :key="column.key"><TableSortButton :label="column.label" :field="column.key" :sort-by="lineSortBy" :sort-order="lineSortOrder" @sort="toggleLineSort" /></th></tr></thead>
            <tbody>
              <tr v-for="(line, index) in sortedLines" :key="line.candidateLineId">
                <td class="detail-sequence-cell">{{ index + 1 }}</td>
                <td class="detail-code" :title="line.sourceSkuId ?? undefined">{{ line.sourceSkuId ?? "—" }}</td>
                <td><strong class="detail-product-name" :title="line.productName ?? undefined">{{ line.productName ?? "—" }}</strong></td>
                <td>{{ line.propertiesValue ?? "—" }}</td>
                <td>
                  <input v-if="candidate.status === 'PENDING'" v-model="draft(line).factoryName" class="pending-detail-input" list="candidate-factory-options" :aria-label="`${line.sourceSkuId ?? index + 1} 工厂`" :disabled="saving || importing" @input="clearSaveError" />
                  <span v-else>{{ line.factoryName ?? "—" }}</span>
                </td>
                <td>
                  <input v-if="candidate.status === 'PENDING'" v-model="draft(line).contractShipDate" class="pending-detail-input" type="date" :aria-label="`${line.sourceSkuId ?? index + 1} 合同出货时间`" :disabled="saving || importing" @input="clearSaveError" />
                  <span v-else>{{ line.contractShipDate || "—" }}</span>
                </td>
                <td class="detail-number">{{ number(line.orderQuantity) }}</td>
                <td class="detail-number">
                  <input v-if="candidate.status === 'PENDING'" v-model="draft(line).shippedQuantity" class="pending-detail-input pending-number-input" type="number" min="0" step="1" :aria-label="`${line.sourceSkuId ?? index + 1} 已发数量`" :disabled="saving || importing" @input="clearSaveError" />
                  <span v-else>{{ number(line.shippedQuantity) }}</span>
                </td>
                <td class="detail-number">{{ number(pending(line)) }}</td>
                <td><span class="detail-progress"><span><i :style="{ width: `${Math.min(progress(line) ?? 0, 100)}%` }"></i></span><em>{{ progress(line) == null ? "—" : `${progress(line)}%` }}</em></span></td>
                <td><span class="status-badge" :class="line.validationIssues.length ? 'is-warning' : 'is-success'">{{ line.validationIssues.length ? "未通过" : "通过" }}</span></td>
              </tr>
            </tbody>
          </table>
          <datalist id="candidate-factory-options"><option v-for="factory in factories" :key="factory.factoryId" :value="factory.factoryName" /></datalist>
        </div>
      </section>

      <section class="section-card detail-section-card pending-import-audit-card">
        <header class="detail-section-header"><h2>操作记录</h2></header>
        <ol v-if="auditLogs.length" class="order-audit-list shipment-log-list">
          <li v-for="log in auditLogs" :key="log.auditId" class="shipment-log-item">
            <span class="shipment-log-dot" aria-hidden="true"></span>
            <div class="shipment-log-content"><div class="shipment-log-heading"><strong>{{ log.operatorName }}</strong><time>{{ formatTime(log.createdAt) }}</time></div><p>{{ auditContent(log) }}</p><span>{{ sourceLabel(log.sourceTerminal) }}</span></div>
          </li>
        </ol>
        <p v-else class="detail-empty-log">暂无操作记录</p>
      </section>

      <p v-if="errorMessage" class="page-error" role="alert">{{ errorMessage }}</p>
      <div v-if="confirmOpen" class="detail-confirm-layer"><button class="detail-confirm-backdrop" type="button" aria-label="取消确认导入" @click="confirmOpen = false"></button><section class="detail-confirm-dialog" role="dialog" aria-modal="true"><h2>确认导入为草稿</h2><p>确认将候选订单 <strong>{{ candidate.orderNo }}</strong> 导入跟单系统？确认后将在订单列表中生成草稿订单，派工前工厂不可见。</p><div class="detail-confirm-actions"><button class="detail-outline-button" type="button" @click="confirmOpen = false">取消</button><button class="detail-primary-button" type="button" :disabled="importing || saving" @click="confirmCandidate">确认导入为草稿</button></div></section></div>
    </article>
    <p v-else-if="loading" class="page-state">正在加载候选订单…</p><p v-else class="page-error">{{ errorMessage }}</p>
  </AdminShell>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";

import { ApiError, identityApi, orderImportApi, type CandidateAuditList, type ImportCandidate } from "@/api/client";
import AdminShell from "@/components/AdminShell.vue";
import TableSortButton from "@/components/TableSortButton.vue";
import { sortedCategories } from "@/productCategories";

type CandidateLine = ImportCandidate["lines"][number];
type LineDraft = { factoryName: string; contractShipDate: string; shippedQuantity: string };

const route = useRoute();
const router = useRouter();
const candidate = ref<ImportCandidate | null>(null);
const factories = ref<Awaited<ReturnType<typeof identityApi.listFactoryOptions>>["items"]>([]);
const auditLogs = ref<CandidateAuditList["items"]>([]);
const drafts = ref<Record<number, LineDraft>>({});
const loading = ref(true);
const saving = ref(false);
const importing = ref(false);
const errorMessage = ref("");
const confirmOpen = ref(false);
const lineSortBy = ref("sourceSkuId");
const lineSortOrder = ref<"asc" | "desc">("asc");

const issueLabels: Record<string, string> = { PRODUCT_VARIANT_NOT_MATCHED: "产品资料未匹配", FACTORY_NOT_MATCHED: "工厂资料未匹配", FACTORY_HAS_NO_ENABLED_USER: "工厂没有已启用账号", INVALID_TRACKER: "跟单人员无效", INVALID_ORDER_QUANTITY: "下单数量无效", INVALID_INITIAL_SHIPPED_QUANTITY: "初始已发数量无效", INITIAL_SHIPPED_EXCEEDS_ORDER_QUANTITY: "初始已发数量大于订单数量", INCONSISTENT_CONTRACT_SHIP_DATE: "合同出货时间待更新" };
const lineColumns = [{ key: "sourceSkuId", label: "产品编码" }, { key: "productName", label: "产品名称" }, { key: "propertiesValue", label: "颜色/规格" }, { key: "factoryName", label: "工厂" }, { key: "contractShipDate", label: "合同出货时间" }, { key: "orderQuantity", label: "下单数量" }, { key: "shippedQuantity", label: "已发数量" }, { key: "pendingQuantity", label: "未发数量" }, { key: "progress", label: "发货进度" }, { key: "validation", label: "校验结果" }];

const number = (value: number | null) => value == null ? "—" : value.toLocaleString("zh-CN");
const issueText = (issues: string[]) => issues.map((issue) => issueLabels[issue] ?? "资料待处理").join("；");
const draft = (line: CandidateLine) => drafts.value[line.candidateLineId]!;
const shipped = (line: CandidateLine) => {
  const value = Number(draft(line)?.shippedQuantity ?? line.shippedQuantity);
  return Number.isInteger(value) && value >= 0 ? value : null;
};
const pending = (line: CandidateLine) => line.orderQuantity == null || shipped(line) == null ? null : Math.max(line.orderQuantity - shipped(line)!, 0);
const progress = (line: CandidateLine) => !line.orderQuantity || shipped(line) == null ? null : Math.round(shipped(line)! * 100 / line.orderQuantity);
const dirty = computed(() => candidate.value?.lines.some((line) => {
  const value = draft(line);
  return value && (value.factoryName !== (line.factoryName ?? "") || value.contractShipDate !== (line.contractShipDate ?? "") || value.shippedQuantity !== (line.shippedQuantity == null ? "" : String(line.shippedQuantity)));
}) ?? false);
const sortedLines = computed(() => [...(candidate.value?.lines ?? [])].sort((left, right) => {
  const value = (line: CandidateLine) => lineSortBy.value === "factoryName" ? draft(line)?.factoryName : lineSortBy.value === "contractShipDate" ? draft(line)?.contractShipDate : lineSortBy.value === "shippedQuantity" ? shipped(line) : lineSortBy.value === "pendingQuantity" ? pending(line) : lineSortBy.value === "progress" ? progress(line) : lineSortBy.value === "validation" ? issueText(line.validationIssues) : line[lineSortBy.value as keyof CandidateLine] ?? "";
  return String(value(left) ?? "").localeCompare(String(value(right) ?? ""), "zh-CN", { numeric: true }) * (lineSortOrder.value === "asc" ? 1 : -1);
}));

function resetDrafts() {
  drafts.value = Object.fromEntries((candidate.value?.lines ?? []).map((line) => [line.candidateLineId, { factoryName: line.factoryName ?? "", contractShipDate: line.contractShipDate ?? "", shippedQuantity: line.shippedQuantity == null ? "" : String(line.shippedQuantity) }]));
}
function toggleLineSort(field: string) { if (lineSortBy.value === field) lineSortOrder.value = lineSortOrder.value === "asc" ? "desc" : "asc"; else { lineSortBy.value = field; lineSortOrder.value = "asc"; } }
function backToList() { return router.push({ path: "/orders/import", query: route.query }); }
function clearSaveError() { errorMessage.value = ""; }
function openConfirm() { errorMessage.value = ""; confirmOpen.value = true; }
function formatTime(value: string) { return new Date(value).toLocaleString("zh-CN", { hour12: false }); }
function sourceLabel(value: string | null) { return value === "web_admin" ? "管理员网页" : value === "mini_program" ? "微信小程序" : "系统"; }
function auditContent(log: CandidateAuditList["items"][number]) {
  if (typeof log.changes.content === "string") return log.changes.content;
  if (log.action === "order_import.detail_updated") return "修改订单明细";
  if (log.action === "order_import.candidate_imported") return "确认导入为草稿";
  return "更新候选订单资料";
}
async function loadAudit() {
  if (!candidate.value) return;
  try { auditLogs.value = (await orderImportApi.auditLogs(candidate.value.candidateId)).items; }
  catch { auditLogs.value = []; }
}
async function saveLines() {
  if (!candidate.value || !dirty.value || saving.value) return;
  const factoryByName = new Map(factories.value.map((factory) => [factory.factoryName, factory.factoryId]));
  let lines;
  try {
    lines = candidate.value.lines.flatMap((line) => {
      const value = draft(line);
      if (!value || (value.factoryName === (line.factoryName ?? "") && value.contractShipDate === (line.contractShipDate ?? "") && value.shippedQuantity === (line.shippedQuantity == null ? "" : String(line.shippedQuantity)))) return [];
      const factoryChanged = value.factoryName !== (line.factoryName ?? "");
      const dateChanged = value.contractShipDate !== (line.contractShipDate ?? "");
      const shippedChanged = value.shippedQuantity !== (line.shippedQuantity == null ? "" : String(line.shippedQuantity));
      const quantity = Number(value.shippedQuantity);
      if (factoryChanged && !factoryByName.has(value.factoryName)) throw new Error("请选择已有工厂");
      if (shippedChanged && (value.shippedQuantity === "" || !Number.isInteger(quantity) || quantity < 0)) throw new Error("已发数量必须为非负整数");
      return [{ candidateLineId: line.candidateLineId, ...(factoryChanged ? { factoryId: factoryByName.get(value.factoryName)! } : {}), ...(dateChanged ? { contractShipDate: value.contractShipDate || null } : {}), ...(shippedChanged ? { shippedQuantity: quantity } : {}) }];
    });
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : "订单明细保存失败";
    return;
  }
  saving.value = true;
  errorMessage.value = "";
  try {
    candidate.value = await orderImportApi.saveLines(candidate.value.candidateId, { version: candidate.value.version, lines });
    resetDrafts();
    await loadAudit();
  } catch (error) {
    errorMessage.value = error instanceof ApiError && error.status === 409 ? "资料已更新，请刷新页面后重新填写" : error instanceof Error ? error.message : "订单明细保存失败";
  } finally { saving.value = false; }
}
async function confirmCandidate() {
  if (!candidate.value || saving.value || importing.value || dirty.value) return;
  importing.value = true;
  try {
    await orderImportApi.confirm(candidate.value.candidateId, candidate.value.version);
    await router.push({ path: "/orders/import", query: { ...route.query, imported: candidate.value.orderNo } });
  } catch (error) { confirmOpen.value = false; errorMessage.value = error instanceof ApiError ? error.message : "导入失败"; }
  finally { importing.value = false; }
}

onMounted(async () => {
  try {
    const [result, factoryResult] = await Promise.all([
      orderImportApi.get(String(route.params.candidateId)),
      identityApi.listFactoryOptions().catch(() => ({ items: [], total: 0 })),
    ]);
    candidate.value = result;
    factories.value = factoryResult.items;
    resetDrafts();
    await loadAudit();
  } catch (error) { errorMessage.value = error instanceof ApiError ? error.message : "候选订单不存在"; }
  finally { loading.value = false; }
});
</script>
