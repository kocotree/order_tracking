<template>
  <AdminShell :title="repair?`返修详情 · ${repair.repairNo}`:'返修详情'">
    <article v-if="repair" class="order-detail-page repair-detail-page">
      <section class="section-card detail-overview-card">
        <header class="detail-page-header">
          <button class="detail-back-button" type="button" @click="router.push('/repairs')"><svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="m15 18-6-6 6-6"/></svg><span>返回</span></button>
          <div class="detail-title-row repair-detail-title"><strong>{{ repair.factoryName }}</strong></div>
        </header>
        <div class="detail-overview-content">
          <dl class="repair-summary-matrix">
            <div><dt>返修数量</dt><dd>{{ n(repair.repairedQuantity) }}</dd></div>
            <div><dt>报废数量</dt><dd>{{ n(repair.scrappedQuantity) }}</dd></div>
            <div><dt>仓库退回总数量</dt><dd>{{ n(repair.warehouseReturnQuantity) }}</dd></div>
            <div><dt>返回总数量</dt><dd>{{ n(repair.returnedQuantity) }}</dd></div>
          </dl>
        </div>
      </section>

      <section class="section-card detail-section-card">
        <header class="detail-section-header"><h2>质检单资料</h2></header>
        <div class="repair-source-file">
          <div class="repair-source-file-icon"><svg viewBox="0 0 40 44" fill="none" aria-hidden="true"><path d="M8 3h16l8 8v30H8V3Z"/><path d="M24 3v9h8M13 21h14M13 27h14M13 33h9"/></svg></div>
          <div><strong>{{ repair.originalFilename }}</strong><span>{{ boxes }} 个箱号 · {{ repair.lines.length }} 条明细 · 仓库退回 {{ n(repair.warehouseReturnQuantity) }} 件</span></div>
          <button class="detail-outline-button" type="button" @click="downloadOriginal">查看或下载</button>
        </div>
        <p v-if="downloadError" class="page-error">{{ downloadError }}</p>
        <div class="detail-table-scroll">
          <table class="detail-data-table repair-quality-table data-grid-table">
            <thead><tr><th scope="col">序号</th><th v-for="column in qualityColumns" :key="column.field" scope="col"><TableSortButton :label="column.label" :field="column.field" :sort-by="qualitySortBy" :sort-order="qualitySortOrder" @sort="sortQuality" /></th></tr></thead>
            <tbody><tr v-for="(row,index) in qualityRows" :key="row.line.inspectionLineId"><td class="order-sequence-cell">{{ index+1 }}</td><td class="detail-code">{{ row.line.sourceSkuId }}</td><td>{{ row.line.productName }}</td><td>{{ row.line.propertiesValue }}</td><td class="repair-number-cell">{{ n(row.line.warehouseReturnQuantity) }}</td><td v-if="row.showBox" class="repair-box-cell" :rowspan="row.boxRowspan">{{ row.line.boxNumber }}</td><td v-if="row.showReason" class="repair-reason-cell" :rowspan="row.reasonRowspan" :title="row.line.reason||'—'">{{ row.line.reason||'—' }}</td></tr></tbody>
          </table>
        </div>
      </section>

      <section class="section-card detail-section-card">
        <header class="detail-section-header"><h2>工厂发回记录</h2></header>
        <div class="detail-table-scroll">
          <table class="detail-data-table repair-return-table data-grid-table">
            <thead><tr><th v-for="column in returnColumns" :key="column.field" scope="col"><TableSortButton :label="column.label" :field="column.field" sort-by="" sort-order="asc" @sort="noop" /></th></tr></thead>
            <tbody><tr><td colspan="8"><div class="repair-inline-empty">工厂尚未提交返修发回记录</div></td></tr></tbody>
          </table>
        </div>
      </section>
    </article>
    <p v-else class="page-state">{{ error||'正在加载返修单…' }}</p>
  </AdminShell>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ApiError, repairApi, type Repair } from "@/api/client";
import AdminShell from "@/components/AdminShell.vue";
import TableSortButton from "@/components/TableSortButton.vue";

type QualityField="sourceSkuId"|"productName"|"propertiesValue"|"warehouseReturnQuantity"|"boxNumber"|"reason";
const qualityColumns:Array<{label:string;field:QualityField}>=[{label:"产品编码",field:"sourceSkuId"},{label:"产品名称",field:"productName"},{label:"颜色/规格",field:"propertiesValue"},{label:"仓库退回数量",field:"warehouseReturnQuantity"},{label:"箱号",field:"boxNumber"},{label:"次品原因",field:"reason"}];
const returnColumns=[{label:"发货日期",field:"shippedDate"},{label:"产品编码",field:"code"},{label:"产品名称",field:"name"},{label:"颜色/规格",field:"colorSpec"},{label:"返修数量",field:"repairedQuantity"},{label:"报废数量",field:"scrappedQuantity"},{label:"返回数量",field:"returnedQuantity"},{label:"仓库退回数量",field:"warehouseReturnQuantity"}];
const route=useRoute(),router=useRouter(),repair=ref<Repair|null>(null),error=ref(""),downloadError=ref("");
const qualitySortBy=ref<QualityField>("sourceOrder" as QualityField),qualitySortOrder=ref<"asc"|"desc">("asc");
const n=(v:number)=>v.toLocaleString("zh-CN");
const boxes=computed(()=>new Set(repair.value?.lines.map(v=>v.boxNumber)).size);
const sortedQualityLines=computed(()=>{const lines=[...(repair.value?.lines??[])];if(qualitySortBy.value===("sourceOrder" as QualityField))return lines.sort((a,b)=>a.sourceOrder-b.sourceOrder);return lines.sort((a,b)=>{const av=a[qualitySortBy.value]??"",bv=b[qualitySortBy.value]??"";const result=typeof av==="number"&&typeof bv==="number"?av-bv:String(av).localeCompare(String(bv),"zh-CN",{numeric:true});return qualitySortOrder.value==="asc"?result:-result;});});
const qualityRows=computed(()=>sortedQualityLines.value.map((line,index,lines)=>{const showBox=index===0||lines[index-1].boxNumber!==line.boxNumber;let boxRowspan=1;if(showBox)while(lines[index+boxRowspan]?.boxNumber===line.boxNumber)boxRowspan++;const reason=line.reason||"";const showReason=index===0||(lines[index-1].reason||"")!==reason;let reasonRowspan=1;if(showReason)while(lines[index+reasonRowspan]&&(lines[index+reasonRowspan].reason||"")===reason)reasonRowspan++;return{line,showBox,boxRowspan,showReason,reasonRowspan};}));
function sortQuality(field:string){const next=field as QualityField;if(qualitySortBy.value===next)qualitySortOrder.value=qualitySortOrder.value==="asc"?"desc":"asc";else{qualitySortBy.value=next;qualitySortOrder.value="asc"}}
function noop(){/* S09 尚无发回记录，保留原型表头交互位置。 */}
async function downloadOriginal(){if(!repair.value)return;downloadError.value="";try{await repairApi.download(repair.value.originalFileId,repair.value.originalFilename)}catch(e){downloadError.value=e instanceof ApiError?e.message:"原始质检单下载失败"}}
onMounted(async()=>{try{repair.value=await repairApi.get(String(route.params.repairId))}catch(e){error.value=e instanceof ApiError?e.message:"返修单加载失败"}});
</script>

<style scoped>
.repair-detail-page{display:grid;gap:14px}.detail-back-button{display:inline-flex;gap:6px;align-items:center}.detail-back-button svg{width:20px;height:20px}.detail-back-button path{stroke:currentColor;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round}.repair-detail-title{gap:12px;font-size:15px;font-weight:800}.repair-summary-matrix{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));grid-template-rows:repeat(2,54px);margin:0;border:1px solid #d8dde5}.repair-summary-matrix>div{display:grid;grid-template-columns:minmax(116px,.8fr) minmax(0,1.2fr);min-width:0;border-right:1px solid #d8dde5;border-bottom:1px solid #d8dde5}.repair-summary-matrix>div:nth-child(2n){border-right:0}.repair-summary-matrix>div:nth-child(n+3){border-bottom:0}.repair-summary-matrix dt,.repair-summary-matrix dd{display:flex;align-items:center;min-width:0;margin:0;padding:0 14px;font-size:13px;font-weight:800}.repair-summary-matrix dt{background:#eef1f5;border-right:1px solid #d8dde5}.repair-source-file{display:grid;grid-template-columns:46px minmax(0,1fr) auto;gap:12px;align-items:center;margin:16px;padding:13px 14px;background:#f8fbfd;border:1px solid #dbe3ea}.repair-source-file-icon{display:grid;width:42px;height:46px;place-items:center;color:#2e9b6d}.repair-source-file-icon svg{width:34px;height:38px}.repair-source-file-icon path{stroke:currentColor;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round}.repair-source-file>div:nth-child(2){display:grid;gap:5px;min-width:0}.repair-source-file strong{overflow:hidden;font-size:13px;font-weight:800;text-overflow:ellipsis;white-space:nowrap}.repair-source-file span{color:var(--subtle);font-size:10px}.repair-quality-table{min-width:1008px;table-layout:fixed}.repair-quality-table th:nth-child(1){width:52px}.repair-quality-table th:nth-child(2){width:120px}.repair-quality-table th:nth-child(3){width:190px}.repair-quality-table th:nth-child(4){width:160px}.repair-quality-table th:nth-child(5){width:112px}.repair-quality-table th:nth-child(6){width:94px}.repair-quality-table th:nth-child(7){width:280px}.repair-quality-table th,.repair-quality-table td{height:40px!important;padding:0 14px!important;text-align:left}.repair-quality-table th:first-child,.repair-quality-table td:first-child{padding-right:8px!important;padding-left:8px!important;text-align:center}.repair-number-cell{font-variant-numeric:tabular-nums}.repair-reason-cell{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;vertical-align:middle}.repair-box-cell{text-align:center;vertical-align:middle}.repair-return-table{min-width:1200px;table-layout:fixed}.repair-return-table th,.repair-return-table td{height:40px!important;padding:0 14px!important}.repair-return-table th:nth-child(1){width:130px}.repair-return-table th:nth-child(2){width:120px}.repair-return-table th:nth-child(3){width:220px}.repair-return-table th:nth-child(4){width:170px}.repair-return-table th:nth-child(n+5){width:120px}.repair-inline-empty{padding:22px;color:var(--subtle);font-size:12px;text-align:center}
@media(max-width:980px){.repair-summary-matrix{grid-template-columns:1fr;grid-template-rows:none}.repair-summary-matrix>div{min-height:54px;border-right:0;border-bottom:1px solid #d8dde5}.repair-summary-matrix>div:nth-child(3){border-bottom:1px solid #d8dde5}}
</style>
