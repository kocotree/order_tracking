<template>
  <AdminShell :title="repair?`返修详情 · ${repair.repairNo}`:'返修详情'">
    <article v-if="repair" class="order-detail-page repair-detail-page">
      <section class="section-card detail-overview-card">
        <header class="detail-page-header">
          <button class="detail-back-button" type="button" @click="goBack"><svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="m15 18-6-6 6-6"/></svg><span>返回</span></button>
          <div class="detail-title-row repair-detail-title"><strong>{{ repair.factoryName }} · {{repair.repairNo}}</strong></div>
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
        <div v-for="file in repair.attachments" :key="file.fileId" class="repair-source-file">
          <div class="repair-source-file-icon"><svg viewBox="0 0 40 44" fill="none" aria-hidden="true"><path d="M8 3h16l8 8v30H8V3Z"/><path d="M24 3v9h8M13 21h14M13 27h14M13 33h9"/></svg></div>
          <div><strong>{{file.filename}}</strong><span>Excel · 原始文件</span></div>
          <button class="detail-outline-button" type="button" @click="downloadOriginal(file)">查看或下载</button>
        </div>
        <p v-if="downloadError" class="page-error">{{downloadError}}</p>
      </section>
      <section class="section-card detail-section-card">
        <header class="detail-section-header"><h2>产品明细</h2></header>
        <div class="detail-table-scroll">
          <table class="detail-data-table repair-product-table data-grid-table">
            <thead><tr><th scope="col">序号</th><th scope="col">产品编码</th><th scope="col">产品名称</th><th scope="col">颜色/规格</th><th scope="col">返修数量</th><th scope="col">报废数量</th><th scope="col">返回总数量/仓库退回数量</th><th scope="col">进度</th></tr></thead>
            <tbody><tr v-for="(item,index) in repair.specs" :key="item.variantId"><td class="order-sequence-cell">{{index+1}}</td><td class="detail-code">{{item.sourceSkuId}}</td><td>{{item.productName}}</td><td>{{item.propertiesValue}}</td><td>{{n(item.repairedQuantity)}}</td><td>{{n(item.scrappedQuantity)}}</td><td>{{n(item.returnedQuantity)}} / {{n(item.warehouseReturnQuantity)}}</td><td>{{item.warehouseReturnQuantity ? Math.round(item.returnedQuantity/item.warehouseReturnQuantity*100) : 0}}%</td></tr></tbody>
          </table>
        </div>
      </section>
    </article>
    <section v-else class="section-card notification-target-error"><button class="detail-back-button" type="button" @click="goBack">‹ 返回</button><p :class="error?'page-error':'page-state'">{{ error||'正在加载返修单…' }}</p></section>
  </AdminShell>
</template>

<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ApiError, repairApi, type Repair, type RepairAttachment } from "@/api/client";
import AdminShell from "@/components/AdminShell.vue";
const route=useRoute(),router=useRouter(),repair=ref<Repair|null>(null),error=ref(""),downloadError=ref("");
const n=(v:number)=>v.toLocaleString("zh-CN");
async function downloadOriginal(file:RepairAttachment){downloadError.value="";try{await repairApi.download(file.fileId,file.filename)}catch(e){downloadError.value=e instanceof ApiError?e.message:"原始质检单下载失败"}}
function goBack(){return router.push(typeof route.query?.notificationReturnTo==="string"?route.query.notificationReturnTo:"/repairs")}
onMounted(async()=>{try{repair.value=await repairApi.get(String(route.params.repairId))}catch(e){error.value=e instanceof ApiError&&e.status===404&&route.query?.notificationReturnTo?"内容已不可查看":e instanceof ApiError?e.message:"返修周期加载失败"}});
</script>

<style scoped>
.repair-detail-page{display:grid;gap:14px}.detail-back-button{display:inline-flex;gap:6px;align-items:center}.detail-back-button svg{width:20px;height:20px}.detail-back-button path{stroke:currentColor;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round}.repair-detail-title{gap:12px;font-size:15px;font-weight:800}.repair-summary-matrix{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));grid-template-rows:repeat(2,54px);margin:0;border:1px solid #d8dde5}.repair-summary-matrix>div{display:grid;grid-template-columns:minmax(116px,.8fr) minmax(0,1.2fr);min-width:0;border-right:1px solid #d8dde5;border-bottom:1px solid #d8dde5}.repair-summary-matrix>div:nth-child(2n){border-right:0}.repair-summary-matrix>div:nth-child(n+3){border-bottom:0}.repair-summary-matrix dt,.repair-summary-matrix dd{display:flex;align-items:center;min-width:0;margin:0;padding:0 14px;font-size:13px;font-weight:800}.repair-summary-matrix dt{background:#eef1f5;border-right:1px solid #d8dde5}.repair-source-file{display:grid;grid-template-columns:46px minmax(0,1fr) auto;gap:12px;align-items:center;margin:16px;padding:13px 14px;background:#f8fbfd;border:1px solid #dbe3ea}.repair-source-file-icon{display:grid;width:42px;height:46px;place-items:center;color:#2e9b6d}.repair-source-file-icon svg{width:34px;height:38px}.repair-source-file-icon path{stroke:currentColor;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round}.repair-source-file>div:nth-child(2){display:grid;gap:5px;min-width:0}.repair-source-file strong{overflow:hidden;font-size:13px;font-weight:800;text-overflow:ellipsis;white-space:nowrap}.repair-source-file span{color:var(--subtle);font-size:10px}.repair-quality-table{min-width:1008px;table-layout:fixed}.repair-quality-table th:nth-child(1){width:52px}.repair-quality-table th:nth-child(2){width:120px}.repair-quality-table th:nth-child(3){width:190px}.repair-quality-table th:nth-child(4){width:160px}.repair-quality-table th:nth-child(5){width:112px}.repair-quality-table th:nth-child(6){width:94px}.repair-quality-table th:nth-child(7){width:280px}.repair-quality-table th,.repair-quality-table td{height:40px!important;padding:0 14px!important;text-align:left}.repair-quality-table th:first-child,.repair-quality-table td:first-child{padding-right:8px!important;padding-left:8px!important;text-align:center}.repair-number-cell{font-variant-numeric:tabular-nums}.repair-reason-cell{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;vertical-align:middle}.repair-box-cell{text-align:center;vertical-align:middle}.repair-return-table{min-width:1200px;table-layout:fixed}.repair-return-table th,.repair-return-table td{height:40px!important;padding:0 14px!important}.repair-return-table th:nth-child(1){width:130px}.repair-return-table th:nth-child(2){width:120px}.repair-return-table th:nth-child(3){width:220px}.repair-return-table th:nth-child(4){width:170px}.repair-return-table th:nth-child(n+5){width:120px}.repair-inline-empty{padding:22px;color:var(--subtle);font-size:12px;text-align:center}
@media(max-width:980px){.repair-summary-matrix{grid-template-columns:1fr;grid-template-rows:none}.repair-summary-matrix>div{min-height:54px;border-right:0;border-bottom:1px solid #d8dde5}.repair-summary-matrix>div:nth-child(3){border-bottom:1px solid #d8dde5}}
.repair-product-table{min-width:1180px;table-layout:fixed}.repair-product-table th:first-child,.repair-product-table td:first-child{width:52px;padding:0 8px!important;text-align:center;white-space:nowrap}.repair-product-table th:nth-child(2){width:160px}.repair-product-table th:nth-child(3){width:22%}.repair-product-table th:nth-child(4){width:18%}.repair-product-table th:nth-child(5),.repair-product-table th:nth-child(6){width:100px}.repair-product-table th:nth-child(7){width:210px}.repair-product-table th:nth-child(8){width:80px}.repair-product-table th,.repair-product-table td{height:40px;padding:0 14px}
</style>
