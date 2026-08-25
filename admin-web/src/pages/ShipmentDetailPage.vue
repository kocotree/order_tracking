<template>
  <AdminShell :title="shipment ? `发货单详情 · ${shipment.shipmentNo}` : '发货单详情'">
    <article v-if="shipment" class="order-detail-page shipment-detail-page">
      <section class="section-card detail-overview-card">
        <header class="detail-page-header">
          <button class="detail-back-button" type="button" @click="router.push('/shipments')"><svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="m15 18-6-6 6-6" /></svg><span>返回</span></button>
        </header>
        <div class="detail-overview-content"><dl class="shipment-summary-grid"><div><dt>关联订单</dt><dd>{{ orderNos }}</dd></div><div><dt>发货时间</dt><dd>{{ displayTime }}</dd></div><div><dt>发货数量</dt><dd class="detail-summary-number">{{ number(shipment.totalQuantity) }}</dd></div><div><dt>总箱数</dt><dd class="detail-summary-number">{{ shipment.totalBoxes }}</dd></div></dl></div>
      </section>

      <section class="section-card detail-section-card">
        <header class="detail-section-header"><h2>发货明细</h2></header>
        <div class="detail-table-scroll"><table class="detail-data-table shipment-product-table data-grid-table">
          <colgroup><col class="detail-sequence-col" /><col class="detail-order-col" /><col class="detail-image-col" /><col class="detail-sku-col" /><col class="detail-product-col" /><col class="detail-properties-col" /><col class="detail-quantity-col" /></colgroup>
          <thead><tr><th class="detail-sequence-column" scope="col">序号</th><th scope="col"><TableSortButton label="关联订单" field="orderNo" :sort-by="lineSortKey" :sort-order="lineSortDirection" @sort="sortLines" /></th><th scope="col">图片</th><th scope="col"><TableSortButton label="产品编码" field="skuId" :sort-by="lineSortKey" :sort-order="lineSortDirection" @sort="sortLines" /></th><th scope="col"><TableSortButton label="产品名称" field="productName" :sort-by="lineSortKey" :sort-order="lineSortDirection" @sort="sortLines" /></th><th scope="col"><TableSortButton label="颜色/规格" field="propertiesValue" :sort-by="lineSortKey" :sort-order="lineSortDirection" @sort="sortLines" /></th><th scope="col"><TableSortButton label="发货数量" field="quantity" :sort-by="lineSortKey" :sort-order="lineSortDirection" @sort="sortLines" /></th></tr></thead>
          <tbody><tr v-for="(line,index) in sortedLines" :key="line.assignmentId"><td class="detail-sequence-cell">{{ index+1 }}</td><td>{{ line.orderNo }}</td><td><span class="product-thumb" aria-label="产品图片未上传"><svg viewBox="0 0 28 34" fill="none" aria-hidden="true"><path d="m9 5 5-2 5 2 5 6-4 3v15H8V14l-4-3 5-6Z" /><path d="M11 5c.6 2 1.6 3 3 3s2.4-1 3-3" /></svg></span></td><td>{{ line.skuId }}</td><td><strong class="detail-product-name">{{ line.productName }}</strong></td><td>{{ line.propertiesValue }}</td><td class="detail-number">{{ number(line.quantity) }}</td></tr></tbody>
        </table></div>
      </section>

      <section class="section-card detail-section-card">
        <header class="detail-section-header"><h2>装箱明细</h2></header>
        <div class="detail-table-scroll"><table class="detail-data-table packing-detail-table data-grid-table">
          <thead><tr><th scope="col">箱号</th><th scope="col"><TableSortButton label="关联订单" field="orderNo" :sort-by="boxSortKey" :sort-order="boxSortDirection" @sort="sortBoxes" /></th><th scope="col"><TableSortButton label="产品编码" field="skuId" :sort-by="boxSortKey" :sort-order="boxSortDirection" @sort="sortBoxes" /></th><th scope="col"><TableSortButton label="产品名称" field="productName" :sort-by="boxSortKey" :sort-order="boxSortDirection" @sort="sortBoxes" /></th><th scope="col"><TableSortButton label="颜色/规格" field="propertiesValue" :sort-by="boxSortKey" :sort-order="boxSortDirection" @sort="sortBoxes" /></th><th scope="col"><TableSortButton label="装箱数量" field="quantity" :sort-by="boxSortKey" :sort-order="boxSortDirection" @sort="sortBoxes" /></th><th scope="col"><TableSortButton label="合计" field="total" :sort-by="boxSortKey" :sort-order="boxSortDirection" @sort="sortBoxes" /></th></tr></thead>
          <tbody v-for="box in sortedBoxes" :key="box.boxNo" class="packing-box-group"><tr v-for="(item,index) in box.items" :key="item.assignmentId"><td v-if="index===0" :rowspan="box.items.length">{{ box.boxNo }}</td><td>{{ item.orderNo }}</td><td>{{ item.skuId }}</td><td>{{ item.productName }}</td><td>{{ item.propertiesValue }}</td><td class="detail-number">{{ number(item.quantity) }}</td><td class="packing-total-cell">{{ index === box.items.length - 1 ? number(boxTotal(box)) : '' }}</td></tr></tbody>
        </table></div>
      </section>

      <section class="shipment-support-grid"><section class="section-card detail-section-card"><header class="detail-section-header"><h2>发货凭证与工厂备注</h2></header><div class="shipment-support-content"><div><h3>发货凭证（0 张）</h3><div class="shipment-proof-empty">工厂未上传发货凭证</div></div><div><h3>工厂备注</h3><p class="shipment-factory-remark">{{ shipment.note || '—' }}</p></div></div></section><section class="section-card detail-section-card"><header class="detail-section-header"><h2>操作记录</h2></header><ol class="shipment-log-list"><li class="shipment-log-item"><span class="shipment-log-dot"></span><div><strong>提交发货单，发货记录立即生效</strong><span>{{ displayTime }} · {{ shipment.factoryName || shipment.factoryId }} · 工厂小程序</span></div></li></ol></section></section>
    </article>
    <p v-else class="page-state">{{ error || '正在加载发货单…' }}</p>
  </AdminShell>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { shipmentApi, type Shipment, type ShipmentBox, type ShipmentLine } from "@/api/client";
import AdminShell from "@/components/AdminShell.vue";
import TableSortButton from "@/components/TableSortButton.vue";
const route = useRoute(); const router = useRouter(); const shipment = ref<Shipment | null>(null); const error = ref(""); const number = (value: number) => value.toLocaleString("zh-CN");
const lineSortKey = ref(""); const lineSortDirection = ref<"asc" | "desc">("asc"); const boxSortKey = ref(""); const boxSortDirection = ref<"asc" | "desc">("asc");
const orderNos = computed(() => [...new Set(shipment.value?.lines.map((line) => line.orderNo) ?? [])].join("、") || "—"); const displayTime = computed(() => shipment.value?.submittedAt ? new Date(shipment.value.submittedAt).toLocaleString("zh-CN", { hour12: false }) : shipment.value?.businessDate || "—");
function compare(a: string | number, b: string | number, direction: "asc" | "desc") { return String(a).localeCompare(String(b), "zh-CN", { numeric: true }) * (direction === "asc" ? 1 : -1); }
function boxTotal(box: ShipmentBox) { return box.items.reduce((sum, item) => sum + item.quantity, 0); }
const sortedLines = computed(() => { const values = [...(shipment.value?.lines ?? [])]; if (!lineSortKey.value) return values; const key = lineSortKey.value as keyof ShipmentLine; return values.sort((a, b) => compare(a[key] as string | number, b[key] as string | number, lineSortDirection.value)); });
const sortedBoxes = computed(() => { const values = (shipment.value?.boxes ?? []).map((box) => ({ ...box, items: [...box.items] })); if (!boxSortKey.value) return values; if (boxSortKey.value === "boxNo" || boxSortKey.value === "total") return values.sort((a, b) => compare(boxSortKey.value === "boxNo" ? a.boxNo : boxTotal(a), boxSortKey.value === "boxNo" ? b.boxNo : boxTotal(b), boxSortDirection.value)); const key = boxSortKey.value as keyof ShipmentLine; return values.map((box) => ({ ...box, items: box.items.sort((a, b) => compare(a[key] as string | number, b[key] as string | number, boxSortDirection.value)) })); });
function sortLines(field: string) { if (lineSortKey.value === field) lineSortDirection.value = lineSortDirection.value === "asc" ? "desc" : "asc"; else { lineSortKey.value = field; lineSortDirection.value = "asc"; } }
function sortBoxes(field: string) { if (boxSortKey.value === field) boxSortDirection.value = boxSortDirection.value === "asc" ? "desc" : "asc"; else { boxSortKey.value = field; boxSortDirection.value = "asc"; } }
onMounted(async () => { try { shipment.value = await shipmentApi.get(String(route.params.shipmentId)); } catch { error.value = "发货单加载失败"; } });
</script>
