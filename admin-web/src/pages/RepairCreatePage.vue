<template>
  <AdminShell title="新建返修单">
    <article class="order-detail-page repair-create-page">
      <section class="section-card detail-overview-card">
        <header class="detail-page-header"><button class="detail-back-button" type="button" @click="router.push('/repairs')">‹ 返回</button><strong>新建返修单</strong></header>
        <div class="repair-upload-content">
          <input ref="excelInput" class="sr-only" type="file" multiple accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" :disabled="busy" @change="selectExcel" />
          <button class="repair-upload-zone" :class="{'is-dragging': dragging}" type="button" :disabled="busy" @click="excelInput?.click()" @dragover.prevent="dragging = !busy" @dragleave.prevent="dragging = false" @drop.prevent="dropExcel">
            <svg viewBox="0 0 48 48" fill="none" aria-hidden="true"><path d="M24 33V12m0 0-8 8m8-8 8 8M10 34v4h28v-4"/></svg>
            <strong>{{ busy ? '正在处理…' : '点击或拖入质检 Excel' }}</strong>
            <span>支持一次上传多个 .xlsx 文件，每个不超过 20 MiB；解析后点击“确认创建”。原始 Excel 完整保留。</span>
          </button>
          <div v-for="item in files" :key="item.id" class="repair-uploaded-file">
            <div><span class="repair-file-mark">XLS</span><span><strong>{{ item.file.name }}</strong><small :class="{'page-error': item.error}">{{ item.error || item.status }}</small></span></div>
            <button v-if="!item.created" class="repair-file-remove" type="button" :aria-label="`移除 ${item.file.name}`" :disabled="busy" @click="removeFile(item.id)">×</button>
          </div>
        </div>
        <footer v-if="files.length" class="repair-create-actions"><button class="detail-outline-button" type="button" :disabled="busy" @click="router.push('/repairs')">返回列表</button><button data-confirm-create class="detail-primary-button" type="button" :disabled="busy || !readyFiles.length" @click="confirmCreate">{{ submitting ? '正在创建…' : '确认创建' }}</button></footer>
      </section>
    </article>
  </AdminShell>
</template>

<script setup lang="ts">
import { computed, ref } from "vue";
import { useRouter } from "vue-router";
import { ApiError, repairApi, type RepairPreview } from "@/api/client";
import AdminShell from "@/components/AdminShell.vue";

type UploadItem = {id:string; file:File; preview:RepairPreview|null; status:string; error:string; key:string; created:boolean};
const router=useRouter(), excelInput=ref<HTMLInputElement|null>(null);
const files=ref<UploadItem[]>([]), uploading=ref(false), submitting=ref(false), dragging=ref(false);
const busy=computed(()=>uploading.value||submitting.value);
const readyFiles=computed(()=>files.value.filter(item=>item.preview?.status==='READY'&&!item.created));
function removeFile(id:string){
  if(busy.value)return;
  files.value=files.value.filter(item=>item.id!==id||item.created);
}
async function receive(selected:File[]){
  if(busy.value||!selected.length)return;
  uploading.value=true;
  const additions=selected.map(file=>({id:crypto.randomUUID(), file, preview:null, status:'等待解析', error:'', key:crypto.randomUUID(), created:false} as UploadItem));
  files.value.push(...additions);
  try {
    for(const source of additions){
      const item=files.value.find(row=>row.id===source.id)!;
      item.status='正在解析';
      try{
        if(item.file.size>20*1024*1024)throw new Error("文件超过 20 MiB，请缩小后重新上传");
        item.preview=await repairApi.upload(item.file);
        item.status=item.preview.status==='READY'?'解析通过，等待确认':'解析失败';
        item.error=item.preview.validationErrors.map(issue=>`${issue.row ? `第 ${issue.row} 行：` : ''}${issue.message}`).join('；');
      }catch(e){item.status='解析失败';item.error=e instanceof ApiError&&e.status===413?'文件超过上传入口大小限制，请缩小文件或联系管理员':e instanceof Error?e.message:'质检 Excel 解析失败';}
    }
  } finally {uploading.value=false;}
}
async function selectExcel(event:Event){const input=event.target as HTMLInputElement;const selected=Array.from(input.files??[]);input.value='';await receive(selected);}
async function dropExcel(event:DragEvent){dragging.value=false;await receive(Array.from(event.dataTransfer?.files??[]));}
async function confirmCreate(){
  if(busy.value)return;
  submitting.value=true;
  const pending=[...readyFiles.value];
  try {
    for(const item of pending){
      item.status='正在创建';item.error='';
      try{await repairApi.confirm(item.preview!.previewId,item.key);item.created=true;item.status='创建成功';}
      catch(e){item.status='创建失败';item.error=e instanceof Error?e.message:'返修单创建失败';}
    }
  } finally {submitting.value=false;}
}
</script>

<style scoped>
.repair-file-remove{flex-shrink:0;width:32px;height:32px;padding:0;border:0;border-radius:4px;background:transparent;color:var(--muted);font-size:24px;cursor:pointer}.repair-file-remove:hover:not(:disabled){background:#fcebea;color:#b42318}.repair-file-remove:disabled{opacity:.4;cursor:not-allowed}.repair-file-remove:focus-visible{outline:2px solid var(--erp-blue);outline-offset:2px}

.repair-create-page{display:grid;gap:14px}.detail-back-button{display:inline-flex;gap:6px;align-items:center}.detail-back-button svg{width:20px;height:20px}.detail-back-button path{stroke:currentColor;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round}.repair-create-title{gap:12px;font-size:15px;font-weight:800}.repair-upload-content{padding:18px}.repair-upload-zone{display:grid;gap:7px;place-items:center;width:100%;min-height:174px;padding:24px;color:var(--muted);font-family:var(--font-body);background:#f8fbfd;border:1px dashed #aebdca;border-radius:6px;cursor:pointer}.repair-upload-zone.is-dragging,.repair-upload-zone:hover,.repair-upload-zone:focus-visible{color:var(--erp-blue-dark);background:#f1f9fe;border-color:var(--erp-blue);outline:none}.repair-upload-zone svg{width:42px;height:42px;color:var(--erp-blue)}.repair-upload-zone path{stroke:currentColor;stroke-width:2.4;stroke-linecap:round;stroke-linejoin:round}.repair-upload-zone strong{color:var(--ink-strong);font-size:15px;font-weight:800}.repair-upload-zone span{max-width:620px;font-size:11px;line-height:1.7;text-align:center}.repair-uploaded-file{display:flex;gap:18px;align-items:center;justify-content:space-between;min-height:82px;padding:14px 16px;background:#f8fbfd;border:1px solid #dbe3ea}.repair-uploaded-file>div,.repair-file-actions{display:flex;gap:12px;align-items:center}.repair-uploaded-file>div>span:last-child{display:grid;gap:4px}.repair-uploaded-file strong{font-size:13px;font-weight:800}.repair-uploaded-file small{color:var(--subtle);font-size:10px}.repair-file-mark{display:grid;width:46px;height:46px;place-items:center;color:#fff;font-size:10px;font-weight:800;background:#2e9b6d;border-radius:4px}.detail-section-header h2,.detail-section-header p{margin:0}.detail-section-header p{color:var(--subtle);font-size:11px}.repair-validation-badge{padding:5px 10px;color:#24744f;font-size:11px;font-weight:700;background:#e9f6ef;border-radius:999px}.repair-preview-summary{display:grid;grid-template-columns:1.5fr repeat(3,1fr);border-bottom:1px solid var(--line)}.repair-preview-summary>div{display:grid;grid-template-columns:minmax(84px,auto) minmax(0,1fr);gap:10px;align-items:center;min-height:58px;padding:10px 14px;border-right:1px solid var(--line)}.repair-preview-summary>:last-child{border-right:0}.repair-preview-summary span{color:var(--muted);font-size:12px;font-weight:700}.repair-preview-summary strong{font-size:17px;font-weight:800}.repair-errors{margin:14px;padding:12px 14px;color:#913d31;background:#fff3f1;border:1px solid #efc4bd}.repair-errors p{margin:4px 0}.repair-preview-table{min-width:1008px;table-layout:fixed}.repair-preview-table th:nth-child(1){width:52px}.repair-preview-table th:nth-child(2){width:120px}.repair-preview-table th:nth-child(3){width:190px}.repair-preview-table th:nth-child(4){width:160px}.repair-preview-table th:nth-child(5){width:112px}.repair-preview-table th:nth-child(6){width:94px}.repair-preview-table th:nth-child(7){width:280px}.repair-preview-table th,.repair-preview-table td{padding:8px 14px;text-align:left}.repair-preview-table th:first-child,.repair-preview-table td:first-child{padding-right:8px!important;padding-left:8px!important;text-align:center}.repair-reason-cell{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.repair-number-cell{font-variant-numeric:tabular-nums}.repair-create-actions{display:flex;gap:10px;justify-content:flex-end;min-height:62px;padding:14px 16px;border-top:1px solid var(--line)}
@media(max-width:980px){.repair-preview-summary{grid-template-columns:repeat(2,minmax(0,1fr))}.repair-preview-summary>:nth-child(2){border-right:0}.repair-preview-summary>:nth-child(-n+2){border-bottom:1px solid var(--line)}}
</style>
