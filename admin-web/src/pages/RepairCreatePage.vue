<template>
  <AdminShell title="新建返修单">
    <article class="order-detail-page repair-create-page">
      <section class="section-card detail-overview-card">
        <header class="detail-page-header">
          <button class="detail-back-button" type="button" @click="router.push('/repairs')"><svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="m15 18-6-6 6-6"/></svg><span>返回</span></button>
          <div class="detail-title-row repair-create-title"><strong>新建返修单</strong></div>
        </header>
        <div class="repair-upload-content">
          <input ref="excelInput" class="sr-only" type="file" accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" @change="selectExcel" />
          <button v-if="!preview" class="repair-upload-zone" type="button" @click="excelInput?.click()">
            <svg viewBox="0 0 48 48" fill="none" aria-hidden="true"><path d="M24 33V12m0 0-8 8m8-8 8 8M10 34v4h28v-4"/></svg>
            <strong>{{ uploading?'正在解析…':'上传质检 Excel' }}</strong>
            <span>仅支持 .xlsx，上传后自动读取工厂、箱号、产品规格、数量和次品原因；原始 Excel 将完整保留并作为附件提供下载。</span>
          </button>
          <div v-else class="repair-uploaded-file">
            <div><span class="repair-file-mark">XLS</span><span><strong>{{ preview.originalFilename }}</strong><small>{{ preview.status==='READY'?'质检单已读取，可以重新上传替换':'存在阻断错误，请重新上传' }}</small></span></div>
            <div class="repair-file-actions"><button class="detail-text-button" type="button" @click="downloadOriginal">查看原文件</button><button class="detail-outline-button" type="button" @click="excelInput?.click()">重新上传</button></div>
          </div>
          <p v-if="error" class="page-error">{{ error }}</p>
        </div>
      </section>

      <section v-if="preview" class="section-card detail-section-card repair-preview-card">
        <header class="detail-section-header"><div><h2>导入预览</h2><p>请核对工厂和明细，确认后系统自动生成返修单号。</p></div><span class="repair-validation-badge">已读取 {{ preview.lineCount }} 条明细</span></header>
        <div class="repair-preview-summary">
          <div><span>工厂</span><strong>{{ preview.factoryName||'未匹配' }}</strong></div>
          <div><span>仓库退回总数量</span><strong>{{ n(preview.totalQuantity) }}</strong></div>
          <div><span>箱数</span><strong>{{ preview.boxCount }}</strong></div>
          <div><span>明细条数</span><strong>{{ preview.lineCount }}</strong></div>
        </div>
        <div v-if="preview.validationErrors.length" class="repair-errors"><strong>发现 {{ preview.validationErrors.length }} 项阻断错误</strong><p v-for="(issue,i) in preview.validationErrors" :key="i">{{ issue.sheet||'文件' }}<template v-if="issue.row"> 第 {{ issue.row }} 行</template>：{{ issue.message }}</p></div>
        <div class="detail-table-scroll">
          <table class="detail-data-table repair-preview-table data-grid-table">
            <thead><tr><th scope="col">序号</th><th v-for="column in columns" :key="column.field" scope="col"><TableSortButton :label="column.label" :field="column.field" :sort-by="sortBy" :sort-order="sortOrder" @sort="sort" /></th></tr></thead>
            <tbody><tr v-for="(line,index) in sortedLines" :key="line.lineId"><td class="order-sequence-cell">{{ index+1 }}</td><td class="detail-code">{{ line.sourceSkuId }}</td><td>{{ line.productName }}</td><td>{{ line.propertiesValue }}</td><td class="repair-number-cell">{{ n(line.quantity) }}</td><td>{{ line.boxNumber }}</td><td class="repair-reason-cell" :title="line.reason||'—'">{{ line.reason||'—' }}</td></tr></tbody>
          </table>
        </div>
        <footer class="repair-create-actions"><button class="detail-outline-button" type="button" @click="router.push('/repairs')">取消</button><button class="detail-primary-button" type="button" :disabled="preview.status!=='READY'||submitting" @click="confirmCreate">{{ submitting?'正在创建…':'确认创建' }}</button></footer>
      </section>
    </article>
  </AdminShell>
</template>

<script setup lang="ts">
import { computed, ref } from "vue";
import { useRouter } from "vue-router";
import { ApiError, repairApi, type RepairPreview } from "@/api/client";
import AdminShell from "@/components/AdminShell.vue";
import TableSortButton from "@/components/TableSortButton.vue";

type SortField="sourceSkuId"|"productName"|"propertiesValue"|"quantity"|"boxNumber"|"reason";
const columns:Array<{label:string;field:SortField}>=[{label:"产品编码",field:"sourceSkuId"},{label:"产品名称",field:"productName"},{label:"颜色/规格",field:"propertiesValue"},{label:"仓库退回数量",field:"quantity"},{label:"箱号",field:"boxNumber"},{label:"次品原因",field:"reason"}];
const router=useRouter(), excelInput=ref<HTMLInputElement|null>(null), preview=ref<RepairPreview|null>(null);
const uploading=ref(false),submitting=ref(false),error=ref("");
const sortBy=ref<SortField|"">(""),sortOrder=ref<"asc"|"desc">("asc");
const sortedLines=computed(()=>{const lines=[...(preview.value?.lines??[])];if(!sortBy.value)return lines;return lines.sort((a,b)=>{const av=a[sortBy.value as SortField]??"",bv=b[sortBy.value as SortField]??"";const result=typeof av==="number"&&typeof bv==="number"?av-bv:String(av).localeCompare(String(bv),"zh-CN",{numeric:true});return sortOrder.value==="asc"?result:-result;});});
const n=(v:number)=>v.toLocaleString("zh-CN");
function sort(field:string){const next=field as SortField;if(sortBy.value===next)sortOrder.value=sortOrder.value==="asc"?"desc":"asc";else{sortBy.value=next;sortOrder.value="asc"}}
function expired(e:unknown){if(e instanceof ApiError&&e.status===409&&e.message.includes("预览已失效")){preview.value=null;error.value="预览已失效，请重新上传质检 Excel";return true}return false}
async function selectExcel(event:Event){const input=event.target as HTMLInputElement;const file=input.files?.[0];if(!file)return;uploading.value=true;error.value="";try{preview.value=await repairApi.upload(file,preview.value?.previewId)}catch(e){if(!expired(e))error.value=e instanceof ApiError?e.message:"质检 Excel 解析失败"}finally{uploading.value=false;input.value=""}}
async function downloadOriginal(){if(!preview.value)return;try{await repairApi.download(preview.value.originalFileId,preview.value.originalFilename)}catch(e){error.value=e instanceof ApiError?e.message:"原始质检单下载失败"}}
async function confirmCreate(){if(!preview.value)return;submitting.value=true;error.value="";try{const repair=await repairApi.confirm(preview.value.previewId);await router.replace(`/repairs/${repair.repairId}`)}catch(e){if(!expired(e))error.value=e instanceof ApiError?e.message:"返修单创建失败"}finally{submitting.value=false}}
</script>

<style scoped>
.repair-create-page{display:grid;gap:14px}.detail-back-button{display:inline-flex;gap:6px;align-items:center}.detail-back-button svg{width:20px;height:20px}.detail-back-button path{stroke:currentColor;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round}.repair-create-title{gap:12px;font-size:15px;font-weight:800}.repair-upload-content{padding:18px}.repair-upload-zone{display:grid;gap:7px;place-items:center;width:100%;min-height:174px;padding:24px;color:var(--muted);font-family:var(--font-body);background:#f8fbfd;border:1px dashed #aebdca;border-radius:6px;cursor:pointer}.repair-upload-zone:hover,.repair-upload-zone:focus-visible{color:var(--erp-blue-dark);background:#f1f9fe;border-color:var(--erp-blue);outline:none}.repair-upload-zone svg{width:42px;height:42px;color:var(--erp-blue)}.repair-upload-zone path{stroke:currentColor;stroke-width:2.4;stroke-linecap:round;stroke-linejoin:round}.repair-upload-zone strong{color:var(--ink-strong);font-size:15px;font-weight:800}.repair-upload-zone span{max-width:620px;font-size:11px;line-height:1.7;text-align:center}.repair-uploaded-file{display:flex;gap:18px;align-items:center;justify-content:space-between;min-height:82px;padding:14px 16px;background:#f8fbfd;border:1px solid #dbe3ea}.repair-uploaded-file>div,.repair-file-actions{display:flex;gap:12px;align-items:center}.repair-uploaded-file>div>span:last-child{display:grid;gap:4px}.repair-uploaded-file strong{font-size:13px;font-weight:800}.repair-uploaded-file small{color:var(--subtle);font-size:10px}.repair-file-mark{display:grid;width:46px;height:46px;place-items:center;color:#fff;font-size:10px;font-weight:800;background:#2e9b6d;border-radius:4px}.detail-section-header h2,.detail-section-header p{margin:0}.detail-section-header p{color:var(--subtle);font-size:11px}.repair-validation-badge{padding:5px 10px;color:#24744f;font-size:11px;font-weight:700;background:#e9f6ef;border-radius:999px}.repair-preview-summary{display:grid;grid-template-columns:1.5fr repeat(3,1fr);border-bottom:1px solid var(--line)}.repair-preview-summary>div{display:grid;grid-template-columns:minmax(84px,auto) minmax(0,1fr);gap:10px;align-items:center;min-height:58px;padding:10px 14px;border-right:1px solid var(--line)}.repair-preview-summary>:last-child{border-right:0}.repair-preview-summary span{color:var(--muted);font-size:12px;font-weight:700}.repair-preview-summary strong{font-size:17px;font-weight:800}.repair-errors{margin:14px;padding:12px 14px;color:#913d31;background:#fff3f1;border:1px solid #efc4bd}.repair-errors p{margin:4px 0}.repair-preview-table{min-width:1008px;table-layout:fixed}.repair-preview-table th:nth-child(1){width:52px}.repair-preview-table th:nth-child(2){width:120px}.repair-preview-table th:nth-child(3){width:190px}.repair-preview-table th:nth-child(4){width:160px}.repair-preview-table th:nth-child(5){width:112px}.repair-preview-table th:nth-child(6){width:94px}.repair-preview-table th:nth-child(7){width:280px}.repair-preview-table th,.repair-preview-table td{padding:8px 14px;text-align:left}.repair-preview-table th:first-child,.repair-preview-table td:first-child{padding-right:8px!important;padding-left:8px!important;text-align:center}.repair-reason-cell{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.repair-number-cell{font-variant-numeric:tabular-nums}.repair-create-actions{display:flex;gap:10px;justify-content:flex-end;min-height:62px;padding:14px 16px;border-top:1px solid var(--line)}
@media(max-width:980px){.repair-preview-summary{grid-template-columns:repeat(2,minmax(0,1fr))}.repair-preview-summary>:nth-child(2){border-right:0}.repair-preview-summary>:nth-child(-n+2){border-bottom:1px solid var(--line)}}
</style>
