<template>
  <AdminShell :title="pageTitle">
    <article class="order-workspace order-detail-page">
      <section v-if="loading" class="section-card page-state">正在加载订单详情…</section>
      <section v-else-if="!order" class="section-card page-error">{{ errorMessage || '订单不存在' }}</section>
      <template v-else>
        <section class="section-card detail-overview-card">
          <header class="detail-page-header">
            <button class="detail-back-button" type="button" @click="$router.push('/orders')"><svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="m15 18-6-6 6-6" /></svg>返回</button>
            <div class="detail-title-row order-detail-actions">
              <span class="status-badge" :class="statusTone(order)"><i aria-hidden="true"></i>{{ order.displayStatus }}</span>
              <RouterLink v-if="order.lifecycle === 'DRAFT'" class="detail-outline-button" :to="`/orders/${order.orderId}/edit`">编辑草稿</RouterLink>
              <button v-if="order.lifecycle === 'DRAFT'" class="detail-primary-button" type="button" @click="openAction('publish')">发布订单</button>
              <button v-if="order.lifecycle === 'PUBLISHED'" class="detail-outline-button" type="button" @click="openAction('withdraw')">撤回订单</button>
              <button v-if="order.lifecycle === 'PUBLISHED'" class="detail-primary-button" type="button" @click="openAction('complete')">确认订单完成</button>
              <button v-if="order.lifecycle === 'COMPLETED'" class="detail-outline-button" type="button" @click="openAction('reopen')">撤销完成</button>
              <button v-if="order.lifecycle !== 'COMPLETED'" class="detail-danger-button" type="button" @click="openAction('delete')">删除订单</button>
            </div>
          </header>
          <div class="detail-overview-content">
            <dl class="detail-summary-grid">
              <div><dt>分类</dt><dd><span v-for="category in categories" :key="category" class="category-tag" :class="category === '帽子' ? 'is-hat' : 'is-clothing'">{{ category }}</span></dd></div>
              <div><dt>跟单人员</dt><dd><span class="tracker-tag" :data-tracker="order.tracker">{{ order.tracker }}</span></dd></div>
              <div><dt>合同出货时间</dt><dd class="detail-due-date">{{ order.contractShipDate }}</dd></div>
              <div><dt>订单数量</dt><dd class="detail-summary-number">{{ number(order.totalQuantity) }}</dd></div>
              <div><dt>已发数量</dt><dd class="detail-summary-number">{{ number(order.shippedQuantity) }}</dd></div>
              <div><dt>未发数量</dt><dd class="detail-summary-number">{{ number(order.pendingQuantity) }}</dd></div>
            </dl>
            <p v-if="order.validationIssues.length" class="validation-callout">{{ order.validationIssues.join('；') }}</p>
          </div>
        </section>

        <section class="section-card detail-section-card">
          <header class="detail-section-header"><h2>订单明细</h2></header>
          <div class="detail-table-scroll">
            <table class="data-grid-table detail-data-table product-detail-table">
              <thead><tr><th class="detail-sequence-column">序号</th><th class="detail-image-column">图片</th><th v-for="column in detailColumns" :key="column.key"><button class="data-grid-sort-button" :class="sortClass(column.key)" type="button" @click="toggleDetailSort(column.key)"><span>{{ column.label }}</span><span class="data-grid-sort-arrows" aria-hidden="true"><i class="data-grid-sort-arrow is-up"></i><i class="data-grid-sort-arrow is-down"></i></span></button></th></tr></thead>
              <tbody><tr v-for="(row, index) in sortedDetailRows" :key="row.key"><td class="detail-sequence-cell">{{ index + 1 }}</td><td class="detail-image-cell"><span class="product-thumb" aria-label="暂无产品图片"><svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="m8 4-4 3 2 4 2-1v10h8V10l2 1 2-4-4-3c-.7 1.2-2 2-4 2S8.7 5.2 8 4Z" /></svg></span></td><td class="detail-code">{{ row.skuId }}</td><td class="detail-product-name">{{ row.productName }}</td><td>{{ row.propertiesValue }}</td><td>{{ row.factoryName }}</td><td class="detail-number">{{ number(row.orderQuantity) }}</td><td class="detail-number">{{ number(row.shippedQuantity) }}</td><td class="detail-number">{{ number(row.pendingQuantity) }}</td><td><span class="detail-progress"><span><i :style="{ width: `${row.progressPercent}%` }"></i></span><em>{{ row.progressPercent }}%</em></span></td></tr></tbody>
            </table>
          </div>
        </section>

        <section class="section-card detail-section-card">
          <header class="detail-section-header"><h2>关联发货单</h2></header>
          <div class="detail-table-scroll"><table class="data-grid-table detail-data-table related-shipment-table"><thead><tr><th>发货单号</th><th>发货日期</th><th>发货数量</th><th>物流单号</th><th>状态</th><th>操作</th></tr></thead><tbody><tr><td class="detail-empty-row" colspan="6">当前订单暂无关联发货单</td></tr></tbody></table></div>
        </section>

      </template>

      <div v-if="pendingAction && order" class="modal-backdrop" role="dialog" aria-modal="true"><section class="modal action-modal"><header><h2>{{ modalTitle }}</h2><button type="button" @click="pendingAction = null">×</button></header><div class="modal-body"><p>{{ modalDescription }}</p><dl v-if="pendingAction === 'complete'" class="completion-summary"><div><dt>订单数量</dt><dd>{{ number(order.totalQuantity) }}</dd></div><div><dt>已发数量</dt><dd>{{ number(order.shippedQuantity) }}</dd></div><div><dt>未发数量</dt><dd>{{ number(order.pendingQuantity) }}</dd></div></dl><label v-if="pendingAction === 'reopen'" class="reopen-field">撤销原因<textarea v-model="reopenReason" maxlength="500" placeholder="请填写撤销完成原因"></textarea></label><p v-if="actionError" class="page-error">{{ actionError }}</p></div><footer><button class="order-secondary-button" type="button" @click="pendingAction = null">取消</button><button class="order-primary-button" type="button" :disabled="acting || (pendingAction === 'reopen' && !reopenReason.trim())" @click="confirmAction">{{ acting ? '处理中…' : '确认' }}</button></footer></section></div>
    </article>
  </AdminShell>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ApiError, orderApi, type Order } from "@/api/client";
import AdminShell from "@/components/AdminShell.vue";

type Action = "publish" | "withdraw" | "delete" | "complete" | "reopen";
type DetailSortKey = "skuId" | "productName" | "propertiesValue" | "factoryName" | "orderQuantity" | "shippedQuantity" | "pendingQuantity" | "progressPercent";
type DetailRow = { key: string; skuId: string; productName: string; propertiesValue: string; factoryName: string; orderQuantity: number; shippedQuantity: number; pendingQuantity: number; progressPercent: number };
const detailColumns: { key: DetailSortKey; label: string }[] = [{ key: "skuId", label: "产品编码" }, { key: "productName", label: "产品名称" }, { key: "propertiesValue", label: "颜色/规格" }, { key: "factoryName", label: "工厂" }, { key: "orderQuantity", label: "下单数量" }, { key: "shippedQuantity", label: "已发数量" }, { key: "pendingQuantity", label: "未发数量" }, { key: "progressPercent", label: "发货进度" }];
const route = useRoute(); const router = useRouter(); const orderId = String(route.params.orderId);
const order = ref<Order | null>(null); const loading = ref(true); const errorMessage = ref(""); const pendingAction = ref<Action | null>(null); const reopenReason = ref(""); const actionError = ref(""); const acting = ref(false); const detailSortKey = ref<DetailSortKey | null>(null); const detailSortOrder = ref<"asc" | "desc">("asc");
const number = (value: number) => value.toLocaleString("zh-CN");
const pageTitle = computed(() => order.value ? `订单详情 · ${order.value.orderNo}` : "订单详情");
const categories = computed(() => { const values = [...new Set(order.value?.lines.map((line) => line.category?.trim()).filter((value): value is string => Boolean(value)) ?? [])]; return values.length ? values : ["未分类"]; });
const detailRows = computed<DetailRow[]>(() => (order.value?.lines ?? []).flatMap((line) => line.assignments.length ? line.assignments.map((assignment) => ({ key: `${line.orderLineId}-${assignment.assignmentId}`, skuId: line.skuId, productName: line.productName, propertiesValue: line.propertiesValue, factoryName: assignment.factoryName, orderQuantity: assignment.assignedQuantity, shippedQuantity: assignment.shippedQuantity, pendingQuantity: assignment.pendingQuantity, progressPercent: assignment.progressPercent })) : [{ key: `${line.orderLineId}-unassigned`, skuId: line.skuId, productName: line.productName, propertiesValue: line.propertiesValue, factoryName: "—", orderQuantity: line.orderQuantity, shippedQuantity: line.shippedQuantity, pendingQuantity: line.pendingQuantity, progressPercent: line.progressPercent }]));
const sortedDetailRows = computed(() => { const key = detailSortKey.value; if (!key) return detailRows.value; const direction = detailSortOrder.value === "asc" ? 1 : -1; return [...detailRows.value].sort((left, right) => String(left[key]).localeCompare(String(right[key]), "zh-CN", { numeric: true }) * direction); });
const modalTitle = computed(() => ({ publish: "发布订单", withdraw: "撤回订单", delete: "删除订单", complete: "确认订单完成", reopen: "撤销完成" }[pendingAction.value ?? "publish"]));
const modalDescription = computed(() => pendingAction.value === "publish" ? "发布后工厂将看到各自派工任务，确认发布？" : pendingAction.value === "withdraw" ? "撤回后订单恢复为草稿，工厂任务将不可见。" : pendingAction.value === "delete" ? "删除后订单不再出现在订单列表和工厂任务中。" : pendingAction.value === "complete" ? "请核对数量摘要。完成状态不会根据发货数量自动产生。" : "撤销后订单恢复为正式订单，并按当前日期重新计算状态。" );
function statusTone(value: Order) { return value.lifecycle === "DRAFT" ? "is-draft" : value.displayStatus === "已逾期" ? "is-danger" : value.lifecycle === "COMPLETED" ? "is-success" : "is-info"; }
function toggleDetailSort(key: DetailSortKey) { if (detailSortKey.value === key) detailSortOrder.value = detailSortOrder.value === "asc" ? "desc" : "asc"; else { detailSortKey.value = key; detailSortOrder.value = "asc"; } }
function sortClass(key: DetailSortKey) { return { "is-sorted": detailSortKey.value === key, "is-sort-desc": detailSortKey.value === key && detailSortOrder.value === "desc" }; }
function openAction(action: Action) { pendingAction.value = action; reopenReason.value = ""; actionError.value = ""; }
async function load() { loading.value = true; try { order.value = await orderApi.get(orderId); } catch (error) { errorMessage.value = error instanceof ApiError ? error.message : "订单详情加载失败"; } finally { loading.value = false; } }
async function confirmAction() { if (!order.value || !pendingAction.value) return; acting.value = true; actionError.value = ""; try { const action = pendingAction.value; if (action === "delete") { await orderApi.delete(orderId); await router.replace("/orders"); return; } if (action === "publish") await orderApi.publish(orderId, order.value.version); if (action === "withdraw") await orderApi.withdraw(orderId); if (action === "complete") await orderApi.complete(orderId); if (action === "reopen") await orderApi.reopen(orderId, reopenReason.value); pendingAction.value = null; await load(); } catch (error) { actionError.value = error instanceof ApiError ? error.message : "订单操作失败"; } finally { acting.value = false; } }
onMounted(load);
</script>
