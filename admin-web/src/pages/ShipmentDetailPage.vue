<template>
  <AdminShell :title="shipment ? `发货单详情 · ${shipment.shipmentNo}` : '发货单详情'">
    <article v-if="shipment" class="order-detail-page shipment-detail-page">
      <section class="section-card detail-overview-card">
        <header class="detail-page-header">
          <button class="detail-back-button" type="button" @click="goBack"><svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="m15 18-6-6 6-6" /></svg><span>返回</span></button>
          <div class="detail-title-row shipment-detail-actions">
            <button v-if="canVerify" class="detail-primary-button" type="button" data-action="confirm-receipt" :disabled="acting || !receiptDraft" @click="confirmReceipt">确认收货</button>
            <span v-else class="status-badge" :class="`is-${statusTone}`">{{ statusLabel }}</span>
            <span v-if="shipment.receipt" class="receipt-confirmation">已收货 · {{ shipment.receipt.confirmedByName }} · {{ receiptTime(shipment.receipt.confirmedAt) }}</span>
            <button v-if="shipment.status !== 'VOIDED'" class="detail-outline-button" type="button" :disabled="acting" @click="downloadWorkbook">下载发货清单</button>
          </div>
        </header>
        <div class="detail-overview-content"><dl class="shipment-summary-grid"><div><dt>关联订单</dt><dd>{{ orderNos }}</dd></div><div><dt>发货时间</dt><dd>{{ displayTime }}</dd></div><div><dt>发货数量</dt><dd class="detail-summary-number">{{ number(displayTotal) }}</dd></div><div><dt>总箱数</dt><dd class="detail-summary-number">{{ shipment.totalBoxes }}</dd></div></dl></div>
      </section>

      <p v-if="receiptError" class="page-error" role="alert">{{ receiptError }} <button type="button" class="detail-outline-button" :disabled="acting" @click="reloadReceipt">重新读取</button></p>
      <p v-if="receiptMessage" :class="receiptDraft ? 'validation-callout' : 'page-state'" role="status">{{ receiptMessage }}</p>
      <section v-if="shipment.voidRequest" class="section-card shipment-void-card">
        <header class="detail-section-header"><h2>撤回申请</h2><span class="status-badge" :class="`is-${voidTone}`">{{ voidLabel }}</span></header>
        <div class="shipment-void-content"><dl><div><dt>申请人</dt><dd>{{ shipment.voidRequest.requestedByName }}</dd></div><div><dt>申请时间</dt><dd>{{ dateTime(shipment.voidRequest.requestedAt) }}</dd></div><div class="is-wide"><dt>撤回原因</dt><dd>{{ shipment.voidRequest.reason }}</dd></div><div v-if="shipment.voidRequest.reviewedAt"><dt>审核时间</dt><dd>{{ dateTime(shipment.voidRequest.reviewedAt) }}</dd></div><div v-if="shipment.voidRequest.reviewComment" class="is-wide"><dt>审核意见</dt><dd>{{ shipment.voidRequest.reviewComment }}</dd></div></dl><div v-if="shipment.voidRequest.status === 'PENDING'" class="shipment-void-actions"><button class="detail-outline-button" type="button" @click="reviewMode = 'reject'">拒绝</button><button class="detail-primary-button" type="button" :disabled="!canApproveVoid" :title="canApproveVoid ? '' : '该发货单已有退回记录，只能拒绝'" @click="reviewMode = 'approve'">通过</button></div></div>
      </section>

      <section class="section-card detail-section-card">
        <header class="detail-section-header"><h2>发货明细</h2><button v-if="canReturn" class="detail-outline-button" type="button" @click="openReturn">退回</button></header>
        <div class="detail-table-scroll"><table class="detail-data-table shipment-product-table data-grid-table">
          <colgroup><col class="detail-sequence-col" /><col class="detail-order-col" /><col class="detail-sku-col" /><col class="detail-product-col" /><col class="detail-properties-col" /><col class="detail-quantity-col" /></colgroup>
          <thead><tr><th class="detail-sequence-column" scope="col">序号</th><th scope="col"><TableSortButton label="关联订单" field="orderNo" :sort-by="lineSortKey" :sort-order="lineSortDirection" @sort="sortLines" /></th><th scope="col"><TableSortButton label="产品编码" field="skuId" :sort-by="lineSortKey" :sort-order="lineSortDirection" @sort="sortLines" /></th><th scope="col"><TableSortButton label="产品名称" field="productName" :sort-by="lineSortKey" :sort-order="lineSortDirection" @sort="sortLines" /></th><th scope="col"><TableSortButton label="颜色/规格" field="propertiesValue" :sort-by="lineSortKey" :sort-order="lineSortDirection" @sort="sortLines" /></th><th scope="col"><TableSortButton label="发货数量" field="quantity" :sort-by="lineSortKey" :sort-order="lineSortDirection" @sort="sortLines" /></th></tr></thead>
          <tbody><tr v-for="(line,index) in sortedLines" :key="line.assignmentId"><td class="detail-sequence-cell">{{ index+1 }}</td><td>{{ line.orderNo }}</td><td>{{ line.skuId }}</td><td><strong class="detail-product-name">{{ line.productName }}</strong></td><td>{{ line.propertiesValue }}</td><td class="detail-number">{{ number(line.quantity) }}</td></tr></tbody>
        </table></div>
      </section>

      <section class="section-card detail-section-card"><header class="detail-section-header"><h2>装箱明细</h2><button v-if="canVerify" type="button" class="detail-outline-button" data-action="save-receipt" :disabled="acting || !receiptDraft" @click="saveReceipt">{{ acting ? "处理中…" : "保存" }}</button></header><div class="detail-table-scroll"><table class="detail-data-table packing-detail-table data-grid-table"><thead><tr><th scope="col">箱号</th><th scope="col">关联订单</th><th scope="col">产品编码</th><th scope="col">产品名称</th><th scope="col">颜色/规格</th><th scope="col">装箱数量</th><th scope="col">合计</th></tr></thead><tbody v-for="box in sortedBoxes" :key="box.boxNo" class="packing-box-group"><tr v-for="(item,index) in box.items" :key="item.assignmentId"><td v-if="index===0" class="packing-box-number" :rowspan="box.items.length">{{ box.boxNo }}</td><td>{{ item.orderNo }}</td><td>{{ item.skuId }}</td><td>{{ item.productName }}</td><td>{{ item.propertiesValue }}</td><td class="detail-number"><input v-if="canVerify && receiptDraft && item.boxItemId" v-model.number="receiptQuantities[item.boxItemId]" class="return-quantity-input" type="number" min="0" max="2147483647" step="1" :disabled="acting" :aria-label="`箱号 ${box.boxNo} ${item.skuId} 核对数量`" /><span v-else>{{ number(item.quantity) }}</span></td><td class="packing-total-cell">{{ index === box.items.length - 1 ? number(boxTotal(box)) : '' }}</td></tr></tbody></table></div></section>

      <section class="shipment-support-grid"><section class="section-card detail-section-card"><header class="detail-section-header"><h2>发货凭证与工厂备注</h2></header><div class="shipment-support-content"><div><h3>发货凭证（{{ shipment.files.length }} 张）</h3><div v-if="shipment.files.length" class="shipment-proof-list"><a v-for="file in shipment.files" :key="file.fileId" class="shipment-proof-item" :href="file.contentUrl" target="_blank" rel="noopener"><img v-show="proofState(file.fileId) !== 'error'" class="shipment-proof-image" :src="file.contentUrl" :alt="`发货凭证 ${file.displayOrder + 1}`" @load="setProofState(file.fileId, 'ready')" @error="setProofState(file.fileId, 'error')" /><span v-if="proofState(file.fileId) === 'loading'">凭证加载中…</span><span v-else-if="proofState(file.fileId) === 'error'">凭证加载失败</span></a></div><div v-else class="shipment-proof-empty">工厂未上传发货凭证</div></div><div><h3>工厂备注</h3><p class="shipment-factory-remark">{{ shipment.note || '—' }}</p></div></div></section><section class="section-card detail-section-card"><header class="detail-section-header"><h2>操作记录</h2></header><ol class="shipment-log-list"><li v-for="event in shipment.returnEvents" :key="event.eventId" class="shipment-log-item"><span class="shipment-log-dot is-warning"></span><div><strong>按发货单退回 {{ number(returnTotal(event)) }} 件</strong><span>{{ event.returnDate }} · {{ event.reason }}</span></div></li><li v-if="shipment.voidRequest" class="shipment-log-item"><span class="shipment-log-dot is-warning"></span><div><strong>提交撤回发货 · {{ voidLabel }}</strong><span>{{ dateTime(shipment.voidRequest.requestedAt) }} · {{ shipment.voidRequest.reason }}</span></div></li><li class="shipment-log-item"><span class="shipment-log-dot"></span><div><strong>提交发货单，发货记录立即生效</strong><span>{{ displayTime }} · {{ shipment.factoryName || shipment.factoryId }} · 工厂小程序</span></div></li></ol></section></section>
    </article>
    <section v-else class="section-card notification-target-error"><button class="detail-back-button" type="button" @click="goBack">‹ 返回</button><p :class="error ? 'page-error' : 'page-state'">{{ error || '正在加载发货单…' }}</p></section>

    <div v-if="reviewMode && shipment?.voidRequest" class="modal-backdrop" role="dialog" aria-modal="true"><section class="modal action-modal"><header><h2>{{ reviewMode === 'approve' ? '确认通过撤回申请' : '拒绝撤回申请' }}</h2><button type="button" @click="reviewMode = null">×</button></header><div class="modal-body"><p v-if="reviewMode === 'approve'">审核通过后将作废整张发货单，并回退发货数量 {{ number(shipment.totalQuantity) }}。</p><label v-else class="reopen-field">审核意见<textarea v-model="reviewComment" maxlength="500" placeholder="请填写拒绝原因"></textarea></label><p v-if="actionError" class="page-error">{{ actionError }}</p></div><footer><button class="detail-outline-button" type="button" @click="reviewMode = null">取消</button><button class="detail-primary-button" type="button" :disabled="acting || (reviewMode === 'reject' && !reviewComment.trim())" @click="confirmReview">{{ acting ? '处理中…' : '确认' }}</button></footer></section></div>

    <div v-if="returnOpen && shipment" class="modal-backdrop" role="dialog" aria-modal="true"><section class="modal shipment-return-dialog"><header><h2>按发货单退回</h2><button type="button" @click="returnOpen = false">×</button></header><div class="modal-body"><div class="detail-table-scroll"><table class="data-grid-table shipment-return-table"><thead><tr><th>选择</th><th>订单编号</th><th>产品编码</th><th>产品名称</th><th>颜色/规格</th><th>发货数量</th><th>可退数量</th><th>本次退回数量</th></tr></thead><tbody><tr v-for="line in returnableLines" :key="line.lineId || line.assignmentId"><td><input v-model="returnSelection[line.lineId || 0]" type="checkbox" /></td><td>{{ line.orderNo }}</td><td>{{ line.skuId }}</td><td>{{ line.productName }}</td><td>{{ line.propertiesValue }}</td><td>{{ number(line.quantity) }}</td><td>{{ number(line.returnableQuantity) }}</td><td><input v-model.number="returnQuantities[line.lineId || 0]" class="return-quantity-input" type="number" min="1" :max="line.returnableQuantity" :disabled="!returnSelection[line.lineId || 0]" /></td></tr></tbody></table></div><label class="return-reason-field">退回原因<textarea v-model="returnReason" maxlength="500" placeholder="请填写本次选中产品共用的退回原因"></textarea></label><p v-if="actionError" class="page-error">{{ actionError }}</p></div><footer><button class="detail-outline-button" type="button" @click="returnOpen = false">取消</button><button class="detail-primary-button" type="button" :disabled="acting" @click="confirmReturn">{{ acting ? '处理中…' : '确认退回' }}</button></footer></section></div>
  </AdminShell>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ApiError, shipmentApi, type Shipment, type ShipmentBox, type ShipmentLine, type ShipmentReturnEvent, type ShipmentReceipt } from "@/api/client";
import AdminShell from "@/components/AdminShell.vue";
import TableSortButton from "@/components/TableSortButton.vue";

const route = useRoute(); const router = useRouter(); const shipment = ref<Shipment | null>(null); const error = ref(""); const acting = ref(false); const actionError = ref("");
const receiptDraft = ref<ShipmentReceipt | null>(null);
const receiptQuantities = ref<Record<number, number | string>>({});
const receiptError = ref(""); const receiptMessage = ref("");
const canVerify = computed(() => shipment.value?.status === "SHIPPED" && !shipment.value.receipt && shipment.value.returnEvents.length === 0);
const receiptDirty = computed(() => !!receiptDraft.value?.items.some(item => receiptQuantities.value[item.boxItemId] !== item.quantity));
const displayBoxes = computed(() => (shipment.value?.boxes ?? []).map(box => ({ ...box, items: box.items.map(item => ({ ...item, quantity: canVerify.value && receiptDraft.value && item.boxItemId ? Number(receiptQuantities.value[item.boxItemId]) || 0 : item.quantity })) })));
const displayLines = computed(() => {
  if (!canVerify.value || !receiptDraft.value) return shipment.value?.lines ?? [];
  const totals = new Map<number, number>();
  for (const box of displayBoxes.value) for (const item of box.items) totals.set(item.assignmentId, (totals.get(item.assignmentId) ?? 0) + item.quantity);
  return (shipment.value?.lines ?? []).map(line => ({ ...line, quantity: totals.get(line.assignmentId) ?? line.quantity }));
});
const displayTotal = computed(() => displayLines.value.reduce((sum, line) => sum + line.quantity, 0));
function useReceipt(value: ShipmentReceipt) { receiptDraft.value = value; receiptQuantities.value = Object.fromEntries(value.items.map(item => [item.boxItemId, item.quantity])); }
async function reloadReceipt() { if (acting.value) return; try { receiptError.value = ""; receiptMessage.value = ""; await load(); } catch { receiptError.value = "核对数据读取失败，请重试"; } }
async function saveReceipt() {
  if (!shipment.value || !receiptDraft.value || acting.value) return;
  const items = receiptDraft.value.items.map(item => ({ boxItemId: item.boxItemId, quantity: receiptQuantities.value[item.boxItemId] }));
  if (items.some(item => typeof item.quantity !== "number" || !Number.isInteger(item.quantity) || item.quantity < 0 || item.quantity > 2147483647)) { receiptError.value = "核对数量必须为非负整数"; return; }
  acting.value = true; receiptError.value = ""; receiptMessage.value = "";
  try { useReceipt(await shipmentApi.saveReceipt(shipment.value.shipmentId, receiptDraft.value.version, items as {boxItemId:number;quantity:number}[])); receiptMessage.value = "核对草稿已保存，确认收货后生效"; }
  catch (value) { receiptError.value = value instanceof ApiError ? value.message : "保存失败，请重试"; }
  finally { acting.value = false; }
}
async function confirmReceipt() {
  if (!shipment.value || !receiptDraft.value || acting.value) return;
  receiptError.value = ""; receiptMessage.value = "";
  if (receiptDirty.value) { receiptError.value = "有未保存的核对数量，请先保存再确认收货"; return; }
  acting.value = true;
  try { shipment.value = await shipmentApi.confirmReceipt(shipment.value.shipmentId, receiptDraft.value.version); receiptDraft.value = null; receiptMessage.value = "收货已确认"; }
  catch (value) { receiptError.value = value instanceof ApiError ? value.message : "确认失败，请重试"; }
  finally { acting.value = false; }
}
function receiptTime(value: string | null | undefined) {
  if (!value) return "—";
  const utc = /(?:Z|[+-]\d{2}:\d{2})$/.test(value) ? value : `${value}Z`;
  return new Date(utc).toLocaleString("zh-CN", { timeZone: "Asia/Shanghai", hour12: false });
}
const proofStates = ref<Record<number, "loading" | "ready" | "error">>({});
const reviewMode = ref<"approve" | "reject" | null>(null); const reviewComment = ref(""); const returnOpen = ref(false); const returnReason = ref(""); const returnSelection = ref<Record<number, boolean>>({}); const returnQuantities = ref<Record<number, number>>({});
const number = (value: number) => value.toLocaleString("zh-CN"); const dateTime = (value: string) => new Date(value).toLocaleString("zh-CN", { hour12: false });
const lineSortKey = ref(""); const lineSortDirection = ref<"asc" | "desc">("asc");
const orderNos = computed(() => [...new Set(shipment.value?.lines.map((line) => line.orderNo) ?? [])].join("、") || "—"); const displayTime = computed(() => shipment.value?.submittedAt ? dateTime(shipment.value.submittedAt) : shipment.value?.businessDate || "—");
const statusLabel = computed(() => ({ SHIPPED: shipment.value?.receipt ? "已收货" : "已发货", VOID_PENDING: "撤回处理中", VOIDED: "已作废" }[shipment.value?.status || "SHIPPED"] || shipment.value?.status)); const statusTone = computed(() => shipment.value?.status === "VOIDED" ? "danger" : shipment.value?.status === "VOID_PENDING" ? "warning" : "success");
const voidLabels: Record<string, string> = { PENDING: "待审核", APPROVED: "已通过", REJECTED: "已拒绝" }; const voidLabel = computed(() => voidLabels[shipment.value?.voidRequest?.status || ""] || ""); const voidTone = computed(() => shipment.value?.voidRequest?.status === "APPROVED" ? "success" : shipment.value?.voidRequest?.status === "REJECTED" ? "danger" : "warning");
const canApproveVoid = computed(() => (shipment.value?.returnEvents.length || 0) === 0); const returnableLines = computed(() => (shipment.value?.lines || []).filter((line) => line.lineId && line.returnableQuantity > 0)); const canReturn = computed(() => shipment.value?.status === "SHIPPED" && returnableLines.value.length > 0);
function compare(a: string | number, b: string | number, direction: "asc" | "desc") { return String(a).localeCompare(String(b), "zh-CN", { numeric: true }) * (direction === "asc" ? 1 : -1); }
function boxTotal(box: ShipmentBox) { return box.items.reduce((sum, item) => sum + item.quantity, 0); } function returnTotal(event: ShipmentReturnEvent) { return event.lines.reduce((sum, line) => sum + line.quantity, 0); }
const sortedLines = computed(() => { const values = [...displayLines.value]; if (!lineSortKey.value) return values; const key = lineSortKey.value as keyof ShipmentLine; return values.sort((a, b) => compare(a[key] as string | number, b[key] as string | number, lineSortDirection.value)); }); const sortedBoxes = computed(() => displayBoxes.value);
function sortLines(field: string) { if (lineSortKey.value === field) lineSortDirection.value = lineSortDirection.value === "asc" ? "desc" : "asc"; else { lineSortKey.value = field; lineSortDirection.value = "asc"; } }
function proofState(fileId: number) { return proofStates.value[fileId] || "loading"; }
function setProofState(fileId: number, state: "ready" | "error") { proofStates.value = { ...proofStates.value, [fileId]: state }; }
async function load() { shipment.value = await shipmentApi.get(String(route.params.shipmentId)); proofStates.value = Object.fromEntries(shipment.value.files.map((file) => [file.fileId, "loading"])); receiptDraft.value = null;
  if (canVerify.value) { try { const value = await shipmentApi.getReceipt(shipment.value.shipmentId); if (value.status === "CONFIRMED") shipment.value = await shipmentApi.get(shipment.value.shipmentId); else useReceipt(value); } catch { receiptError.value = "核对数据读取失败，请重新读取"; } }
}
function goBack() { return router.push(typeof route.query.notificationReturnTo === "string" ? route.query.notificationReturnTo : "/shipments"); }
async function downloadWorkbook() { if (!shipment.value) return; acting.value = true; actionError.value = ""; try { await shipmentApi.download(shipment.value); } catch (value) { actionError.value = value instanceof ApiError ? value.message : "下载失败"; } finally { acting.value = false; } }
async function confirmReview() { if (!shipment.value?.voidRequest || !reviewMode.value) return; acting.value = true; actionError.value = ""; try { if (reviewMode.value === "approve") await shipmentApi.approveVoid(shipment.value.voidRequest.requestId); else await shipmentApi.rejectVoid(shipment.value.voidRequest.requestId, reviewComment.value.trim()); reviewMode.value = null; reviewComment.value = ""; await load(); } catch (value) { actionError.value = value instanceof ApiError ? value.message : "审核失败"; } finally { acting.value = false; } }
function openReturn() { actionError.value = ""; returnReason.value = ""; returnSelection.value = {}; returnQuantities.value = {}; returnOpen.value = true; }
async function confirmReturn() { if (!shipment.value) return; const lines = returnableLines.value.filter((line) => line.lineId && returnSelection.value[line.lineId]).map((line) => ({ shipmentLineId: line.lineId as number, quantity: Number(returnQuantities.value[line.lineId as number]) })); if (!lines.length || lines.some((line) => !Number.isInteger(line.quantity) || line.quantity <= 0) || !returnReason.value.trim()) { actionError.value = "请选择明细，填写正整数退回数量和退回原因"; return; } acting.value = true; actionError.value = ""; try { await shipmentApi.createReturn(shipment.value.shipmentId, returnReason.value.trim(), lines); returnOpen.value = false; await load(); } catch (value) { actionError.value = value instanceof ApiError ? value.message : "退回失败"; } finally { acting.value = false; } }
onMounted(async () => { try { await load(); } catch (value) { error.value = value instanceof ApiError && value.status === 404 && route.query.notificationReturnTo ? "内容已不可查看" : value instanceof ApiError ? value.message : "发货单加载失败"; } });
</script>
