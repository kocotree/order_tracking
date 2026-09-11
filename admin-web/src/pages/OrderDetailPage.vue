<template>
  <AdminShell :title="pageTitle">
    <article class="order-workspace order-detail-page dispatch-page">
      <section v-if="loading" class="section-card page-state">正在加载订单详情…</section>
      <section v-else-if="!order" class="section-card notification-target-error"><button class="detail-back-button" type="button" @click="goBack">‹ 返回</button><p class="page-error">{{ errorMessage || '订单不存在' }}</p></section>
      <template v-else>
        <section class="section-card detail-overview-card">
          <header class="detail-page-header">
            <button class="detail-back-button" type="button" @click="goBack"><svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="m15 18-6-6 6-6" /></svg>返回</button>
            <div class="detail-title-row order-detail-actions">
              <span class="status-badge" :class="statusTone(order)"><i aria-hidden="true"></i>{{ order.displayStatus }}</span>
              <button v-if="order.lifecycle === 'DRAFT' && !order.detailMode" class="detail-primary-button" type="button" @click="openAction('publish')">发布订单</button>
              <button class="detail-outline-button" type="button" data-testid="contract-export-open" :disabled="!contractButtonEnabled" :title="contractButtonTitle" @click="openContractExport">导出加工合同</button>
              <button v-if="order.lifecycle === 'PUBLISHED' && !order.detailMode" class="detail-outline-button" type="button" @click="openAction('withdraw')">撤回订单</button>
              <button v-if="order.lifecycle === 'PUBLISHED' && !order.detailMode" class="detail-primary-button" type="button" @click="openAction('complete')">确认订单完成</button>
              <button v-if="order.lifecycle === 'COMPLETED'" class="detail-outline-button" type="button" @click="openAction('reopen')">撤销完成</button>
            </div>
          </header>
          <div class="detail-overview-content">
            <dl class="detail-summary-grid">
              <div><dt>分类</dt><dd><span v-for="category in categories" :key="category" class="category-tag" :class="category === '帽子' ? 'is-hat' : 'is-clothing'">{{ category }}</span></dd></div>
              <div><dt>跟单人员</dt><dd><span class="tracker-tag" :data-tracker="order.tracker">{{ order.tracker ?? "—" }}</span></dd></div>
              <div><dt>合同出货时间</dt><dd class="detail-due-date">{{ order.contractShipDates.join("、") || "—" }}</dd></div>
              <div><dt>订单数量</dt><dd class="detail-summary-number">{{ number(order.totalQuantity) }}</dd></div>
              <div><dt>已发数量</dt><dd class="detail-summary-number">{{ number(order.shippedQuantity) }}</dd></div>
              <div><dt>未发数量</dt><dd class="detail-summary-number">{{ number(order.pendingQuantity) }}</dd></div>
            </dl>
            <p v-if="order.validationIssues.length" class="validation-callout">{{ order.validationIssues.join('；') }}</p>
          </div>
        </section>

        <section class="section-card detail-section-card">
          <header class="detail-section-header">
            <div class="dispatch-heading"><h2>订单明细</h2><span v-if="order.detailMode" class="dispatch-count">已派工 {{ dispatchedCount }}/{{ detailRows.length }} 条 · {{ dispatchProgressLabel }}</span></div>
            <div v-if="hasUnassigned" class="dispatch-actions">
              <button class="detail-outline-button" type="button" :disabled="interactionBusy || hasUnsavedDates || sourcePreview !== null" @click="previewSource">更新未派工明细</button>
              <button class="detail-primary-button" type="button" :disabled="!selectedDetails.size || interactionBusy || hasUnsavedDates || sourcePreview !== null" @click="previewDispatch">派工（已选 {{ selectedDetails.size }} 条）</button>
            </div>
          </header>
          <p v-if="sourceError" class="page-error" role="alert">{{ sourceError }}</p>
          <div class="detail-table-scroll">
            <table class="data-grid-table product-detail-table dispatch-table" :class="{ 'has-selection': hasUnassigned }">
              <colgroup>
                <col v-if="hasUnassigned" style="width:40px">
                <col style="width:52px">
                <col style="width:160px">
                <col>
                <col style="width:130px">
                <col style="width:125px">
                <col style="width:90px">
                <col style="width:170px">
                <col style="width:105px">
                <col style="width:105px">
                <col style="width:95px">
                <col style="width:135px">
              </colgroup>
              <thead><tr>
                <th v-if="hasUnassigned" class="dispatch-check"><input type="checkbox" :checked="allSelected" :disabled="interactionBusy" aria-label="选择全部未派工明细" @change="toggleAll($event)"></th>
                <th class="dispatch-seq">序号</th>
                <th v-for="column in detailColumns" :key="column.key" :class="{ 'dispatch-name-column': column.key === 'productName' }"><button class="data-grid-sort-button" :class="sortClass(column.key)" type="button" @click="toggleDetailSort(column.key)"><span>{{ column.label }}</span><span class="data-grid-sort-arrows" aria-hidden="true"><i class="data-grid-sort-arrow is-up"></i><i class="data-grid-sort-arrow is-down"></i></span></button></th>
              </tr></thead>
              <tbody><tr v-for="(row, index) in sortedDetailRows" :key="row.key">
                <td v-if="hasUnassigned" class="dispatch-check">
                  <input v-if="!row.dispatched" type="checkbox" :checked="selectedDetails.has(row.key)" :disabled="interactionBusy" :aria-label="`选择第${index + 1}条`" @change="toggleRow(row.key, $event)">
                </td>
                <td class="dispatch-seq">{{ index + 1 }}</td>
                <td class="dispatch-code">{{ row.skuId }}</td>
                <td class="dispatch-name" :title="row.productName">{{ row.productName }}</td>
                <td>{{ row.propertiesValue }}</td>
                <td :title="row.factoryName">{{ row.factoryName }}</td>
                <td><span class="status-badge" :class="row.dispatched ? 'is-info' : 'is-draft'">{{ row.dispatched ? '已派工' : '未派工' }}</span></td>
                <td><input v-if="isEditable(row.key)" class="source-contract-date" type="date" :aria-label="`第${index + 1}条合同出货时间`" :value="dateDrafts[row.key] ?? row.contractShipDate" :disabled="interactionBusy || sourcePreview !== null || dispatchSourcePreview !== null" @input="dateDrafts[row.key] = ($event.target as HTMLInputElement).value" @blur="saveDetailDate(row.key)"><template v-else>{{ row.contractShipDate || "—" }}</template></td>
                <td class="detail-number">{{ number(row.orderQuantity) }}</td>
                <td class="detail-number">{{ number(row.shippedQuantity) }}</td>
                <td class="detail-number">{{ number(row.pendingQuantity) }}</td>
                <td><span class="detail-progress"><span><i :style="{ width: `${Math.min(row.progressPercent ?? 0, 100)}%` }"></i></span><em>{{ row.progressPercent == null ? "—" : `${row.progressPercent}%` }}</em></span></td>
              </tr></tbody>
            </table>
          </div>
        </section>

        <section class="section-card detail-section-card">
          <header class="detail-section-header"><h2>关联发货单</h2></header>
          <div class="detail-table-scroll"><table class="data-grid-table detail-data-table related-shipment-table"><thead><tr><th>发货单号</th><th>发货日期</th><th>发货数量</th><th>操作</th></tr></thead><tbody>
            <tr v-if="shipmentsLoading"><td colspan="4" class="detail-empty-row">正在加载关联发货单…</td></tr>
            <tr v-else-if="shipmentsError"><td colspan="4" class="detail-empty-row" role="alert">{{ shipmentsError }}</td></tr>
            <template v-else>
              <tr v-for="shipment in relatedShipments" :key="shipment.shipmentId">
                <td><RouterLink class="row-link" :to="`/shipments/${shipment.shipmentId}`">{{ shipment.shipmentNo }}</RouterLink></td>
                <td>{{ shipment.businessDate || "—" }}</td><td>{{ shipment.totalQuantity.toLocaleString() }}</td>
                <td><RouterLink class="row-link" :to="`/shipments/${shipment.shipmentId}`">详情</RouterLink></td>
              </tr>
              <tr v-if="!relatedShipments.length"><td class="detail-empty-row" colspan="4">当前订单暂无关联发货单</td></tr>
            </template>
          </tbody></table></div>
        </section>

        <section class="section-card detail-section-card order-audit-card" :class="{ 'is-expanded': auditExpanded }">
          <button class="order-audit-toggle" type="button" :aria-expanded="auditExpanded" aria-controls="order-audit-list" :disabled="!auditLogs.length" @click="auditExpanded = !auditExpanded">
            <span class="order-audit-toggle-title">操作记录<em>（{{ auditLogs.length }}）</em></span>
            <span class="order-audit-toggle-action">{{ auditLogs.length ? (auditExpanded ? '收起' : '展开') : '暂无记录' }}<svg v-if="auditLogs.length" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="m8 10 4 4 4-4" /></svg></span>
          </button>
          <ol v-if="auditExpanded && auditLogs.length" id="order-audit-list" class="order-audit-list shipment-log-list">
            <li v-for="(log, index) in auditLogs" :key="`${log.createdAt}-${index}`" class="shipment-log-item">
              <span class="shipment-log-dot" :class="{ 'is-warning': isQuantityRollback(log.action) }" aria-hidden="true"></span>
              <div><strong>{{ log.content }}</strong><span>{{ dateTime(log.createdAt) }} · {{ log.operatorName }} · {{ sourceTerminalLabel(log.sourceTerminal) }}</span></div>
            </li>
          </ol>
        </section>

      </template>

      <dialog ref="sourceDialog" class="modal source-update-modal" aria-labelledby="source-update-title" @cancel="cancelSource" @close="onSourceClosed">
        <header><h2 id="source-update-title">更新未派工明细</h2><button type="button" aria-label="关闭" :disabled="sourceBusy" @click="cancelSource">×</button></header>
        <div class="modal-body">
          <p>{{ sourcePreview?.differences.length ? '来源资料有变化，请确认后更新。已派工明细和人工填写的合同出货时间保持不变。' : '未派工明细没有可更新的来源变化，人工填写的合同出货时间已保留。' }}</p>
          <table v-if="sourcePreview?.differences.length"><thead><tr><th>明细</th><th>字段</th><th>当前值</th><th>来源新值</th></tr></thead><tbody><tr v-for="(change, index) in sourcePreview.differences" :key="index"><td>{{ change.label }}</td><td>{{ change.field }}</td><td>{{ change.before ?? '—' }}</td><td>{{ change.after ?? '—' }}</td></tr></tbody></table>
          <p v-if="sourceError" class="page-error" role="alert">{{ sourceError }}</p>
        </div>
        <footer><button class="order-secondary-button" type="button" :disabled="sourceBusy" @click="cancelSource">取消</button><button v-if="sourcePreview?.differences.length" class="order-primary-button" type="button" :disabled="sourceBusy" @click="confirmSource">{{ sourceBusy ? '更新中…' : '确认' }}</button></footer>
      </dialog>

      <dialog ref="dispatchDialog" class="modal dispatch-modal" aria-labelledby="dispatch-dialog-title" @cancel="cancelDispatch" @close="onDispatchClosed">
        <header><h2 id="dispatch-dialog-title">{{ dispatchStep === 'source' ? '更新未派工明细' : '确认派工' }}</h2><button type="button" aria-label="关闭" :disabled="dispatchBusy" @click="cancelDispatch">×</button></header>
        <div class="modal-body" v-if="dispatchStep === 'source'">
          <p>来源资料有变化，请确认后继续派工。已派工明细和人工填写的合同出货时间保持不变。</p>
          <table><thead><tr><th>明细</th><th>字段</th><th>当前值</th><th>来源新值</th></tr></thead><tbody><tr v-for="(change, index) in dispatchSourcePreview?.differences ?? []" :key="index"><td>{{ change.label }}</td><td>{{ change.field }}</td><td>{{ change.before ?? '—' }}</td><td>{{ change.after ?? '—' }}</td></tr></tbody></table>
        </div>
        <div class="modal-body" v-else>
          <p>{{ dispatchPreview?.allOk ? '所选明细校验通过。确认后对应工厂可以查看本次派工明细。' : '所选明细存在未通过项，本次不会派工。请取消勾选或补齐资料后重试。' }}</p>
          <table><thead><tr><th>明细</th><th>工厂</th><th>校验结果</th></tr></thead><tbody><tr v-for="item in dispatchPreview?.validations ?? []" :key="item.detailId"><td>{{ item.label }}</td><td>{{ item.factoryName }}</td><td :class="item.passes ? 'dispatch-pass' : 'dispatch-error'">{{ item.passes ? '通过' : item.issues.join('；') }}</td></tr></tbody></table>
          <p v-if="dispatchError" class="page-error" role="alert">{{ dispatchError }}</p>
        </div>
        <footer>
          <button class="order-secondary-button" type="button" :disabled="dispatchBusy" @click="cancelDispatch">取消</button>
          <button v-if="dispatchStep === 'source'" class="order-primary-button" type="button" :disabled="dispatchBusy" @click="confirmDispatchSource">确认</button>
          <button v-else-if="dispatchPreview?.allOk" class="order-primary-button" type="button" :disabled="dispatchBusy" @click="confirmDispatchAction">{{ dispatchBusy ? '派工中…' : '确认' }}</button>
        </footer>
      </dialog>

      <div v-if="pendingAction && order" class="modal-backdrop" role="dialog" aria-modal="true">
        <!-- existing action modal unchanged -->
        <section class="modal action-modal"><header><h2>{{ modalTitle }}</h2><button type="button" @click="pendingAction = null">×</button></header><div class="modal-body"><p>{{ modalDescription }}</p><dl v-if="pendingAction === 'complete'" class="completion-summary"><div><dt>订单数量</dt><dd>{{ number(order.totalQuantity) }}</dd></div><div><dt>已发数量</dt><dd>{{ number(order.shippedQuantity) }}</dd></div><div><dt>未发数量</dt><dd>{{ number(order.pendingQuantity) }}</dd></div></dl><label v-if="pendingAction === 'reopen'" class="reopen-field">撤销原因<textarea v-model="reopenReason" maxlength="500" placeholder="请填写撤销完成原因"></textarea></label><p v-if="actionError" class="page-error">{{ actionError }}</p></div><footer><button class="order-secondary-button" type="button" @click="pendingAction = null">取消</button><button class="order-primary-button" type="button" :disabled="acting || (pendingAction === 'reopen' && !reopenReason.trim())" @click="confirmAction">{{ acting ? '处理中…' : '确认' }}</button></footer></section>
      </div>

      <div v-if="contractDialogOpen && order" class="modal-backdrop" role="dialog" aria-modal="true" aria-labelledby="contract-export-title">
        <section class="modal contract-export-dialog" :class="{ 'is-factory-list': !selectedContractFactory && contractFactories.length > 1 }">
          <header><h2 id="contract-export-title">导出加工合同</h2><button type="button" aria-label="关闭导出加工合同弹窗" @click="closeContractExport">×</button></header>
          <div v-if="!selectedContractFactory && contractFactories.length > 1" class="contract-export-body">
            <p class="contract-export-intro">订单 {{ order.orderNo }} 包含多个工厂，请选择需要导出合同的工厂。</p>
            <div class="contract-factory-table-wrap"><table class="contract-factory-table"><thead><tr><th>工厂</th><th>合同资料</th><th>合同编号</th><th>签订日期</th><th>操作</th></tr></thead><tbody><tr v-for="factory in contractFactories" :key="factory.factoryId"><td><strong>{{ factory.factoryName }}</strong></td><td><span class="contract-ready-badge" :class="factory.contractReady ? 'is-ready' : 'is-missing'">{{ contractReadyLabel(factory) }}</span></td><td>{{ factory.contractNo || '首次导出后生成' }}</td><td>{{ factory.signingDate || localDate() }}</td><td><button class="detail-text-button" type="button" :disabled="!factory.eligible" @click="selectContractFactory(factory)">导出</button></td></tr></tbody></table></div>
          </div>
          <template v-else-if="selectedContractFactory">
            <div class="contract-export-body"><dl class="contract-export-summary"><div><dt>订单编号</dt><dd>{{ order.orderNo }}</dd></div><div><dt>工厂</dt><dd>{{ selectedContractFactory.factoryName }}</dd></div><div><dt>合同资料</dt><dd><span class="contract-ready-badge" :class="selectedContractFactory.contractReady ? 'is-ready' : 'is-missing'">{{ contractReadyLabel(selectedContractFactory) }}</span></dd></div><div><dt>合同编号</dt><dd>{{ selectedContractFactory.contractNo || '首次导出后生成' }}</dd></div></dl><label class="contract-date-field"><span>签订日期</span><input v-model="contractSigningDate" type="date" :readonly="Boolean(selectedContractFactory.contractNo)"></label><p v-if="selectedContractFactory.contractNo" class="contract-repeat-hint">将按首次合同快照重新生成，合同编号和签订日期不变。</p><p v-if="!selectedContractFactory.contractReady" class="contract-export-warning">该工厂的合同资料不完整，暂不能导出。请先在工厂资料中补全工厂代码、单位全称、单位地址和法定代表人。</p><p v-if="contractError" class="page-error contract-export-error">{{ contractError }}</p></div>
            <footer><button class="order-secondary-button" type="button" @click="closeContractExport">取消</button><button class="order-primary-button" type="button" :disabled="exportingContract || !selectedContractFactory.eligible" @click="confirmContractExport">{{ exportingContract ? '生成中…' : '确认导出' }}</button></footer>
          </template>
        </section>
      </div>
    </article>
  </AdminShell>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ApiError, contractApi, orderApi, shipmentApi, type Shipment, type AuditLogList, type ContractFactoryStatus, type Order, type SourcePreview, type DispatchPreview } from "@/api/client";
import AdminShell from "@/components/AdminShell.vue";

const relatedShipments = ref<Shipment[]>([]);
const shipmentsLoading = ref(false);
const shipmentsError = ref("");
async function loadShipments() {
  const target = orderId; shipmentsLoading.value = true; shipmentsError.value = "";
  try { const result = await shipmentApi.list(target); if (target === orderId) relatedShipments.value = result.items; }
  catch { if (target === orderId) shipmentsError.value = "关联发货单加载失败，请刷新重试"; }
  finally { if (target === orderId) shipmentsLoading.value = false; }
}

type Action = "publish" | "withdraw" | "delete" | "complete" | "reopen";
type DetailSortKey = "skuId" | "productName" | "propertiesValue" | "factoryName" | "dispatched" | "contractShipDate" | "orderQuantity" | "shippedQuantity" | "pendingQuantity" | "progressPercent";
type DetailRow = { key: string; skuId: string; productName: string; propertiesValue: string; factoryName: string; dispatched: boolean; contractShipDate: string; orderQuantity: number | null; shippedQuantity: number | null; pendingQuantity: number | null; progressPercent: number | null };
const detailColumns: { key: DetailSortKey; label: string }[] = [{ key: "skuId", label: "产品编码" }, { key: "productName", label: "产品名称" }, { key: "propertiesValue", label: "颜色/规格" }, { key: "factoryName", label: "工厂" }, { key: "dispatched", label: "派工状态" }, { key: "contractShipDate", label: "合同出货时间" }, { key: "orderQuantity", label: "下单数量" }, { key: "shippedQuantity", label: "已发数量" }, { key: "pendingQuantity", label: "未发数量" }, { key: "progressPercent", label: "发货进度" }];
const route = useRoute(); const router = useRouter(); let orderId = String(route.params.orderId);
const order = ref<Order | null>(null); const loading = ref(true); const errorMessage = ref(""); const pendingAction = ref<Action | null>(null); const reopenReason = ref(""); const actionError = ref(""); const acting = ref(false); const detailSortKey = ref<DetailSortKey | null>(null); const detailSortOrder = ref<"asc" | "desc">("asc");

// Source update state
const sourceBusy = ref(false);
const sourceError = ref("");
const dateDrafts = ref<Record<string, string>>({});
const sourcePreview = ref<SourcePreview | null>(null);
const sourceDialog = ref<HTMLDialogElement | null>(null);
let sourceEpoch = 0;
let sourceKey = "";

// Dispatch state
const dispatchBusy = ref(false);
const dispatchError = ref("");
const dispatchPreview = ref<DispatchPreview | null>(null);
const dispatchDialog = ref<HTMLDialogElement | null>(null);
const dispatchStep = ref<"source" | "validate">("validate");
const dispatchSourcePreview = ref<SourcePreview | null>(null);
const selectedDetails = ref(new Set<string>());
let dispatchKey = "";
let dispatchSourceKey = "";
let dispatchEpoch = 0;
const interactionBusy = computed(() => sourceBusy.value || dispatchBusy.value);

const isEditable = (id: string) => order.value?.detailMode ? order.value.details.find((row) => row.detailId === id && row.dispatchState === "UNASSIGNED") : undefined;
const hasUnassigned = computed(() => order.value?.detailMode && order.value.details.some((row) => row.dispatchState === "UNASSIGNED"));
const dispatchedCount = computed(() => order.value?.detailMode ? order.value.details.filter((row) => row.dispatchState === "ASSIGNED").length : 0);
const dispatchProgressLabel = computed(() => {
  if (!order.value?.detailMode) return "";
  const total = order.value.details.length;
  const dispatched = dispatchedCount.value;
  if (dispatched === 0) return "未派工";
  if (dispatched < total) return "部分派工";
  return "全部派工";
});
const allSelected = computed(() => {
  const unassigned = detailRows.value.filter((r) => !r.dispatched);
  return unassigned.length > 0 && unassigned.every((r) => selectedDetails.value.has(r.key));
});

function toggleAll(event: Event) {
  const checked = (event.target as HTMLInputElement).checked;
  detailRows.value.filter((r) => !r.dispatched).forEach((r) => {
    if (checked) selectedDetails.value.add(r.key);
    else selectedDetails.value.delete(r.key);
  });
}
function toggleRow(key: string, event: Event) {
  const checked = (event.target as HTMLInputElement).checked;
  if (checked) selectedDetails.value.add(key);
  else selectedDetails.value.delete(key);
}

const hasUnsavedDates = computed(() => Object.entries(dateDrafts.value).some(([id, value]) => value !== (isEditable(id)?.contractShipDate ?? "")));
function currentSource(epoch: number, id: string) { return epoch === sourceEpoch && String(route.params.orderId) === id; }
function currentDispatch(epoch: number, id: string) { return epoch === dispatchEpoch && String(route.params.orderId) === id; }

async function saveDetailDate(id: string) {
  const detail = isEditable(id);
  if (!order.value || !detail || interactionBusy.value || sourcePreview.value || dispatchSourcePreview.value) return;
  const value = dateDrafts.value[id];
  if (value === undefined || value === (detail.contractShipDate ?? "")) return;
  const epoch = ++sourceEpoch, target = orderId;
  sourceBusy.value = true; sourceError.value = "";
  try {
    const saved = await orderApi.saveDetailDate(target, id, order.value.version, detail.version, value || null);
    if (!currentSource(epoch, target)) return;
    order.value = saved; delete dateDrafts.value[id];
    void loadAudit();
  } catch (error) {
    if (currentSource(epoch, target)) sourceError.value = error instanceof ApiError ? `${error.message}；日期尚未保存，请重试，版本冲突时刷新页面。` : "日期保存失败，输入已保留，请重新聚焦后离开输入框重试。";
  } finally { if (currentSource(epoch, target)) sourceBusy.value = false; }
}

async function previewSource() {
  if (!order.value || interactionBusy.value || hasUnsavedDates.value || sourcePreview.value) return;
  const epoch = ++sourceEpoch, target = orderId;
  sourceBusy.value = true; sourceError.value = "";
  try {
    const preview = await orderApi.previewSource(target, order.value.version);
    if (!currentSource(epoch, target)) return;
    sourcePreview.value = preview; sourceKey = crypto.randomUUID();
    await nextTick();
    if (currentSource(epoch, target)) sourceDialog.value?.showModal();
  } catch (error) {
    if (currentSource(epoch, target)) sourceError.value = error instanceof ApiError ? error.message : "来源读取失败，原资料保持不变，请重试。";
  } finally { if (currentSource(epoch, target)) sourceBusy.value = false; }
}
function onSourceClosed() { if (!sourceDialog.value?.open) sourcePreview.value = null; }
function cancelSource(event?: Event) {
  if (sourceBusy.value) { event?.preventDefault(); return; }
  sourceEpoch++; sourcePreview.value = null; sourceDialog.value?.close(); sourceError.value = "";
}
async function confirmSource() {
  const preview = sourcePreview.value;
  if (!preview || sourceBusy.value) return;
  const epoch = ++sourceEpoch, target = orderId;
  sourceBusy.value = true; sourceError.value = "";
  try {
    const saved = await orderApi.confirmSource(target, preview.version, preview.previewId, sourceKey);
    if (!currentSource(epoch, target)) return;
    order.value = saved; sourcePreview.value = null; sourceDialog.value?.close();
    void loadAudit();
  } catch (error) {
    if (currentSource(epoch, target)) sourceError.value = error instanceof ApiError ? error.message : "来源更新失败，请重试。";
  } finally { if (currentSource(epoch, target)) sourceBusy.value = false; }
}

// Dispatch flow: preview → (source changes?) → confirm
async function previewDispatch() {
  if (!order.value || interactionBusy.value || hasUnsavedDates.value || sourcePreview.value || selectedDetails.value.size === 0) return;
  const epoch = ++dispatchEpoch, target = orderId;
  dispatchBusy.value = true; dispatchError.value = "";
  const detailIds = [...selectedDetails.value];
  try {
    const preview = await orderApi.dispatchPreview(target, order.value.version, detailIds);
    if (!currentDispatch(epoch, target)) return;
    if (preview.requiresSourceConfirmation && preview.sourcePreview) {
      dispatchSourcePreview.value = preview.sourcePreview;
      dispatchSourceKey = crypto.randomUUID();
      dispatchStep.value = "source";
    } else {
      dispatchPreview.value = preview;
      dispatchStep.value = "validate";
      dispatchKey = crypto.randomUUID();
    }
    await nextTick();
    if (currentDispatch(epoch, target)) dispatchDialog.value?.showModal();
  } catch (error) {
    if (currentDispatch(epoch, target)) dispatchError.value = error instanceof ApiError ? error.message : "派工检查失败，请重试。";
  } finally { if (currentDispatch(epoch, target)) dispatchBusy.value = false; }
}

function onDispatchClosed() { if (!dispatchDialog.value?.open) { dispatchPreview.value = null; dispatchSourcePreview.value = null; } }
function cancelDispatch(event?: Event) {
  if (dispatchBusy.value) { event?.preventDefault(); return; }
  dispatchEpoch++; dispatchPreview.value = null; dispatchDialog.value?.close(); dispatchError.value = ""; dispatchSourcePreview.value = null;
}

async function confirmDispatchSource() {
  const source = dispatchSourcePreview.value;
  if (!order.value || !source || dispatchBusy.value) return;
  const epoch = ++dispatchEpoch, target = orderId;
  dispatchBusy.value = true; dispatchError.value = "";
  try {
    const saved = await orderApi.confirmSource(target, source.version, source.previewId, dispatchSourceKey);
    if (!currentDispatch(epoch, target)) return;
    order.value = saved;
    const detailIds = [...selectedDetails.value];
    const preview = await orderApi.dispatchPreview(target, saved.version, detailIds);
    if (!currentDispatch(epoch, target)) return;
    if (preview.requiresSourceConfirmation && preview.sourcePreview) {
      dispatchSourcePreview.value = preview.sourcePreview;
      dispatchSourceKey = crypto.randomUUID();
    } else {
      dispatchSourcePreview.value = null;
      dispatchPreview.value = preview;
      dispatchStep.value = "validate";
      dispatchKey = crypto.randomUUID();
    }
  } catch (error) {
    if (currentDispatch(epoch, target)) dispatchError.value = error instanceof ApiError ? error.message : "来源更新后派工检查失败，请重试。";
  } finally { if (currentDispatch(epoch, target)) dispatchBusy.value = false; }
}

async function confirmDispatchAction() {
  const preview = dispatchPreview.value;
  if (!preview?.previewId || !preview.allOk || dispatchBusy.value || !order.value) return;
  const epoch = ++dispatchEpoch, target = orderId;
  dispatchBusy.value = true; dispatchError.value = "";
  try {
    const saved = await orderApi.dispatchConfirm(target, preview.version, preview.previewId, dispatchKey);
    if (!currentDispatch(epoch, target)) return;
    order.value = saved;
    selectedDetails.value.clear();
    dispatchPreview.value = null;
    dispatchDialog.value?.close();
    void loadAudit();
    void loadContracts();
  } catch (error) {
    if (currentDispatch(epoch, target)) dispatchError.value = error instanceof ApiError ? error.message : "派工失败，请重试。";
  } finally { if (currentDispatch(epoch, target)) dispatchBusy.value = false; }
}

onUnmounted(() => { sourceEpoch++; dispatchEpoch++; });
watch(() => route.params.orderId, () => {
  sourceEpoch++; dispatchEpoch++;
  orderId = String(route.params.orderId); sourceBusy.value = false; dispatchBusy.value = false;
  sourcePreview.value = null; sourceDialog.value?.close(); sourceError.value = "";
  dispatchPreview.value = null; dispatchDialog.value?.close(); dispatchError.value = "";
  dispatchSourcePreview.value = null; selectedDetails.value.clear();
  dateDrafts.value = {}; order.value = null; relatedShipments.value = []; auditLogs.value = [];
  contractFactories.value = []; pendingAction.value = null; contractDialogOpen.value = false;
  void load();
});
const auditLogs = ref<AuditLogList["items"]>([]);
const auditExpanded = ref(false);
const contractFactories = ref<ContractFactoryStatus[]>([]); const loadingContracts = ref(false); const contractDialogOpen = ref(false); const selectedContractFactory = ref<ContractFactoryStatus | null>(null); const contractSigningDate = ref(""); const contractError = ref(""); const exportingContract = ref(false);
const number = (value: number | null) => value == null ? "—" : value.toLocaleString("zh-CN");
const dateTime = (value: string) => new Date(value).toLocaleString("zh-CN", { timeZone: "Asia/Shanghai", hour12: false });
const pageTitle = computed(() => order.value ? `订单详情 · ${order.value.orderNo}` : "订单详情");
const contractButtonEnabled = computed(() => order.value?.lifecycle === "PUBLISHED" && contractFactories.value.length > 0 && !loadingContracts.value);
const contractButtonTitle = computed(() => order.value?.lifecycle === "DRAFT" ? "请先发布订单后再导出加工合同" : order.value?.lifecycle !== "PUBLISHED" ? "只有已发布订单才能导出加工合同" : contractFactories.value.length === 0 ? "订单尚未派工，不能导出加工合同" : "导出加工合同");
const categories = computed(() => { const values = [...new Set((order.value?.detailMode ? order.value.details : order.value?.lines)?.map((line) => line.category?.trim()).filter((value): value is string => Boolean(value)) ?? [])]; return values.length ? values : ["未分类"]; });
const detailRows = computed(() => {
  const rows: DetailRow[] = order.value?.detailMode
    ? order.value.details.map((detail): DetailRow => ({ key: detail.detailId, skuId: detail.sourceSkuId ?? "—", productName: detail.productName ?? "—", propertiesValue: detail.propertiesValue ?? "—", factoryName: detail.factoryName ?? "—", dispatched: detail.dispatchState === "ASSIGNED", contractShipDate: detail.contractShipDate ?? "", orderQuantity: detail.orderQuantity, shippedQuantity: detail.shippedQuantity, pendingQuantity: detail.pendingQuantity, progressPercent: detail.progressPercent }))
    : (order.value?.lines ?? []).flatMap((line) => line.assignments.length
      ? line.assignments.map((assignment): DetailRow => ({ key: `${line.orderLineId}-${assignment.assignmentId}`, skuId: line.skuId, productName: line.productName, propertiesValue: line.propertiesValue, factoryName: assignment.factoryName, dispatched: true, contractShipDate: assignment.contractShipDate ?? "", orderQuantity: assignment.assignedQuantity, shippedQuantity: assignment.shippedQuantity, pendingQuantity: assignment.pendingQuantity, progressPercent: assignment.progressPercent }))
      : [{ key: `${line.orderLineId}-unassigned`, skuId: line.skuId, productName: line.productName, propertiesValue: line.propertiesValue, factoryName: "—", dispatched: false, contractShipDate: "", orderQuantity: line.orderQuantity, shippedQuantity: line.shippedQuantity, pendingQuantity: line.pendingQuantity, progressPercent: line.progressPercent } as DetailRow]);
  return rows;
});
const sortedDetailRows = computed(() => { const key = detailSortKey.value; if (!key) return detailRows.value; const direction = detailSortOrder.value === "asc" ? 1 : -1; return [...detailRows.value].sort((left, right) => { const a = left[key]; const b = right[key]; if (typeof a === "boolean" && typeof b === "boolean") return (a === b ? 0 : a ? 1 : -1) * direction; return String(a).localeCompare(String(b), "zh-CN", { numeric: true }) * direction; }); });
const modalTitle = computed(() => ({ publish: "发布订单", withdraw: "撤回订单", delete: "删除订单", complete: "确认订单完成", reopen: "撤销完成" }[pendingAction.value ?? "publish"]));
const modalDescription = computed(() => pendingAction.value === "publish" ? "发布后工厂将看到各自派工任务，确认发布？" : pendingAction.value === "withdraw" ? "撤回后订单恢复为草稿，工厂任务将不可见。" : pendingAction.value === "delete" ? "删除后订单不再出现在订单列表和工厂任务中。" : pendingAction.value === "complete" ? "请核对数量摘要。完成状态不会根据发货数量自动产生。" : "撤销后订单恢复为正式订单，并按当前日期重新计算状态。" );
function statusTone(value: Order) { return value.lifecycle === "DRAFT" ? "is-draft" : value.displayStatus === "已逾期" ? "is-danger" : value.lifecycle === "COMPLETED" ? "is-success" : "is-info"; }
function isQuantityRollback(action: string) { return action === "shipment_void_approved" || action === "shipment_line_returned"; }
function sourceTerminalLabel(source: string | null) { const labels: Record<string, string> = { web: "管理员网页", "admin-web": "管理员网页", web_admin: "管理员网页", "admin-mini": "管理员小程序", "factory-mini": "工厂小程序" }; return source ? (labels[source] || source) : "系统"; }
function toggleDetailSort(key: DetailSortKey) { if (detailSortKey.value === key) detailSortOrder.value = detailSortOrder.value === "asc" ? "desc" : "asc"; else { detailSortKey.value = key; detailSortOrder.value = "asc"; } }
function sortClass(key: DetailSortKey) { return { "is-sorted": detailSortKey.value === key, "is-sort-desc": detailSortKey.value === key && detailSortOrder.value === "desc" }; }
function openAction(action: Action) { pendingAction.value = action; reopenReason.value = ""; actionError.value = ""; }
function localDate() { const now = new Date(); return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`; }
function contractReadyLabel(factory: ContractFactoryStatus) { const labels: Record<string, string> = { factoryCode: "工厂代码", legalName: "单位全称", address: "单位地址", legalRepresentative: "法定代表人" }; return factory.contractReady ? "完整" : `缺少：${factory.missingContractFields.map((field) => labels[field] || field).join("、")}`; }
async function loadAudit() {
  const target = orderId;
  try { const result = await orderApi.auditLogs(target); if (target === orderId) auditLogs.value = result.items; }
  catch { /* Order writes have already succeeded; log reload does not change their result. */ }
}
async function loadContracts() {
  if (order.value?.lifecycle !== "PUBLISHED") { contractFactories.value = []; return; }
  const target = orderId; loadingContracts.value = true;
  try { const result = await contractApi.list(target); if (target === orderId) contractFactories.value = result.items; }
  catch (error) { if (target === orderId) contractError.value = error instanceof ApiError ? error.message : "合同状态加载失败"; }
  finally { if (target === orderId) loadingContracts.value = false; }
}
async function load() {
  const target = orderId; loading.value = true; errorMessage.value = "";
  try {
    const result = await orderApi.get(target);
    if (target !== orderId) return;
    order.value = result;
    await Promise.all([loadShipments(), loadAudit(), loadContracts()]);
  } catch (error) {
    if (target === orderId) errorMessage.value = error instanceof ApiError && error.status === 404 && route.query?.notificationReturnTo ? "内容已不可查看" : error instanceof ApiError ? error.message : "订单详情加载失败";
  } finally { if (target === orderId) loading.value = false; }
}
function goBack() { return router.push(typeof route.query.notificationReturnTo === "string" ? route.query.notificationReturnTo : "/orders"); }
function selectContractFactory(factory: ContractFactoryStatus) { selectedContractFactory.value = factory; contractSigningDate.value = factory.signingDate || localDate(); contractError.value = ""; }
function openContractExport() { if (!order.value) return; contractError.value = ""; contractDialogOpen.value = true; if (contractFactories.value.length === 1) selectContractFactory(contractFactories.value[0]); else selectedContractFactory.value = null; }
function closeContractExport() { contractDialogOpen.value = false; selectedContractFactory.value = null; contractError.value = ""; }
async function confirmContractExport() { const factory = selectedContractFactory.value; if (!factory || !contractSigningDate.value) return; exportingContract.value = true; contractError.value = ""; try { const exported = await contractApi.export(orderId, factory.factoryId, contractSigningDate.value); await contractApi.download(exported); closeContractExport(); await loadContracts(); } catch (error) { contractError.value = error instanceof ApiError ? error.message : "加工合同导出失败"; } finally { exportingContract.value = false; } }
async function confirmAction() { if (!order.value || !pendingAction.value) return; acting.value = true; actionError.value = ""; try { const action = pendingAction.value; if (action === "delete") { await orderApi.delete(orderId); await router.replace("/orders"); return; } if (action === "publish") await orderApi.publish(orderId, order.value.version); if (action === "withdraw") await orderApi.withdraw(orderId); if (action === "complete") await orderApi.complete(orderId); if (action === "reopen") await orderApi.reopen(orderId, reopenReason.value); pendingAction.value = null; await load(); } catch (error) { actionError.value = error instanceof ApiError ? error.message : "订单操作失败"; } finally { acting.value = false; } }
onMounted(load);
</script>

<style scoped>
.source-contract-date { width: 100%; min-width: 0; height: 32px; padding: 0 7px; border: 1px solid #d3dbe6; border-radius: 4px; background: white; color: inherit; font: inherit; }
.source-update-modal { width: min(880px, calc(100vw - 40px)); padding: 0; }
.source-update-modal::backdrop { background: rgb(20 31 43 / 40%); }
.source-update-modal .modal-body { max-height: 65vh; overflow: auto; }
.source-update-modal table { width: 100%; border-collapse: collapse; margin-top: 16px; font-size: 14px; }
.source-update-modal th, .source-update-modal td { padding: 12px; border: 1px solid #dde1e7; text-align: left; }
.source-update-modal th { background: #f1f3f6; }

/* Dispatch-specific styles */
.dispatch-page .detail-section-header { height: 54px; padding: 0 16px; display: flex; align-items: center; justify-content: space-between; }
.dispatch-page .detail-section-header h2 { font-size: 18px; }
.dispatch-heading, .dispatch-actions { display: flex; align-items: center; gap: 14px; white-space: nowrap; }
.dispatch-count { color: var(--muted); font-size: 13px; font-weight: 500; }
.dispatch-table { width: 100%; min-width: 1550px; table-layout: fixed; border-collapse: collapse; font-size: 14px; }
.dispatch-table th, .dispatch-table td { box-sizing: border-box; border: 1px solid #dde1e7; padding: 0 14px; text-align: left; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.dispatch-table th { height: 40px; font-size: 13px; font-weight: 800; background: #f1f3f6; color: #37404b; }
.dispatch-table td { height: 48px; font-weight: 700; }
.dispatch-table .dispatch-seq { width: 52px; min-width: 52px; max-width: 52px; padding: 0 8px; text-align: center; font-weight: 700; }
.dispatch-table th.dispatch-seq { font-weight: 800; }
.dispatch-table .dispatch-check { width: 40px; min-width: 40px; max-width: 40px; padding: 0 8px; text-align: center; }
.dispatch-table .dispatch-name-column, .dispatch-table .dispatch-name { width: calc(100% - 1167px); }
.dispatch-table.has-selection .dispatch-name-column, .dispatch-table.has-selection .dispatch-name { width: calc(100% - 1207px); }
.dispatch-table input:not([type=checkbox]) { width: 100%; min-width: 0; height: 32px; padding: 0 7px; border: 1px solid #d3dbe6; border-radius: 4px; background: white; color: inherit; font: inherit; }
.dispatch-table input[type=checkbox] { width: 15px; height: 15px; accent-color: var(--erp-blue); }
.dispatch-table .dispatch-code { color: var(--erp-blue-dark); font-weight: 700; }
.dispatch-table .dispatch-name { overflow: hidden; text-overflow: ellipsis; }
.dispatch-table .detail-number { font-weight: 700; }
.dispatch-modal { width: min(880px, calc(100vw - 40px)); padding: 0; }
.dispatch-modal::backdrop { background: rgb(20 31 43 / 40%); }
.dispatch-modal .modal-body { max-height: 65vh; overflow: auto; }
.dispatch-modal table { width: 100%; border-collapse: collapse; margin-top: 16px; font-size: 14px; }
.dispatch-modal th, .dispatch-modal td { padding: 12px; border: 1px solid #dde1e7; text-align: left; }
.dispatch-modal th { background: #f1f3f6; }
.dispatch-modal .dispatch-error { color: #b45309; font-weight: 700; }
.dispatch-modal .dispatch-pass { color: #18764b; font-weight: 700; }
.dispatch-modal p { margin: 0; }
@media (max-width: 1100px) { .dispatch-page .detail-section-header { overflow-x: auto; gap: 24px; } }
</style>
