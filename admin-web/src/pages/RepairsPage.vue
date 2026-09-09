<template>
  <AdminShell title="返修退回">
    <article class="order-list-page repair-list-page">
      <section class="order-list-filter-card repair-filter-card" aria-label="返修单筛选">
        <form class="order-filter-form" @submit.prevent="search">
          <div class="order-filter-row repair-filter-row">
            <label class="order-list-search-field">
              <span class="sr-only">搜索返修单号或工厂名称</span>
              <svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><circle cx="11" cy="11" r="6.5"/><path d="m16 16 4 4"/></svg>
              <input v-model="keyword" type="search" placeholder="输入返修单号或工厂名称" autocomplete="off" />
            </label>
            <label class="order-select-field repair-status-field">
              <span class="sr-only">选择返修状态</span>
              <select v-model="status"><option value="all">全部状态</option><option value="INCOMPLETE">未完成</option><option value="COMPLETED">已完成</option></select>
            </label>
            <div class="order-multiselect repair-factory-field">
              <button class="order-multiselect-trigger" type="button" :aria-expanded="factoryMenuOpen" @click="factoryMenuOpen = !factoryMenuOpen">
                <span>{{ factoryLabel }}</span>
                <svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="m7 9 5 5 5-5"/></svg>
              </button>
              <div v-if="factoryMenuOpen" class="order-multiselect-menu">
                <strong>选择工厂（可多选）</strong>
                <label v-for="name in factories" :key="name" class="order-multiselect-option"><input v-model="factoryFilter" type="checkbox" :value="name" /><span>{{ name }}</span></label>
                <span v-if="!factories.length" class="order-multiselect-empty">暂无工厂</span>
              </div>
            </div>
            <label class="order-date-field"><span class="sr-only">退回开始日期</span><input v-model="dateFrom" type="date" /></label>
            <span class="order-date-separator">—</span>
            <label class="order-date-field"><span class="sr-only">退回结束日期</span><input v-model="dateTo" type="date" /></label>
            <button class="order-secondary-button" type="button" @click="reset">重置</button>
            <button class="order-primary-button" type="submit">搜索</button>
          </div>
        </form>
      </section>

      <section class="section-card order-list-card">
        <header class="order-list-card-header repair-list-header">
          <div class="order-list-heading"><h1>返修退回</h1></div>
          <button class="order-primary-button repair-create-button" type="button" @click="router.push('/repairs/new')">新建返修单</button>
        </header>
        <p v-if="error || optionsError" class="page-error">{{ error || optionsError }}</p>
        <div class="table-scroll">
          <table class="orders-table repair-list-table data-grid-table">
            <thead><tr>
              <th class="order-sequence-column" scope="col">序号</th>
              <th v-for="column in sortableColumns" :key="column.field" scope="col"><TableSortButton :label="column.label" :field="column.field" :sort-by="sortBy" :sort-order="sortOrder" @sort="sort" /></th>
              <th scope="col">操作</th>
            </tr></thead>
            <tbody>
              <tr v-for="(item,index) in pageItems" :key="item.repairId">
                <td class="order-sequence-cell">{{ (page-1)*pageSize+index+1 }}</td>
                <td><button class="row-link" type="button" @click="open(item.repairId)">{{ item.repairNo }}</button></td>
                <td>{{ item.factoryName }}</td>
                <td class="repair-number-cell">{{ n(item.repairedQuantity) }}</td>
                <td class="repair-number-cell">{{ n(item.scrappedQuantity) }}</td>
                <td class="repair-number-cell">{{ n(item.returnedQuantity) }}</td>
                <td class="repair-number-cell">{{ n(item.warehouseReturnQuantity) }}</td>
                <td>{{ item.returnDate }}</td>
                <td><span class="status-badge" :class="item.status==='COMPLETED'?'is-success':'is-info'">{{ item.status==='COMPLETED'?'已完成':'未完成' }}</span></td>
                <td><div class="order-row-actions"><button class="order-view-button" type="button" @click="open(item.repairId)">详情</button><button v-if="item.status==='COMPLETED'" class="order-view-button repair-archive-button" type="button" @click="archiveTarget=item">归档</button></div></td>
              </tr>
              <tr v-if="!loading&&!pageItems.length"><td colspan="10"><div class="empty-state"><div><span class="empty-state-mark">0</span><strong>没有符合当前条件的返修单</strong><p>可以调整返修单号、状态、工厂或退回时间范围后重新查询。</p></div></div></td></tr>
            </tbody>
          </table>
        </div>
        <footer class="order-list-footer repair-list-footer">
          <span>每页展示 10 条返修单。</span>
          <NumberPagination :page="page" :total="total" :loading="loading" @change="page = $event" />
        </footer>
      </section>
      <div v-if="archiveTarget" class="detail-confirm-layer">
        <button class="detail-confirm-backdrop" type="button" aria-label="取消归档返修单" @click="archiveTarget=null"></button>
        <section class="detail-confirm-dialog order-delete-dialog" role="dialog" aria-modal="true" aria-labelledby="repair-archive-title" aria-describedby="repair-archive-description">
          <h2 id="repair-archive-title">归档返修单</h2>
          <p id="repair-archive-description">确认归档返修单 <strong>{{ archiveTarget.repairNo }}</strong>？归档后管理员和工厂小程序均不再显示。</p>
          <div class="detail-confirm-actions">
            <button class="detail-outline-button" type="button" :disabled="archiving" @click="archiveTarget=null">取消</button>
            <button class="order-primary-button" data-repair-archive-confirm type="button" :disabled="archiving" @click="confirmArchive">{{ archiving?'归档中…':'确认归档' }}</button>
          </div>
        </section>
      </div>
    </article>
  </AdminShell>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useRouter } from "vue-router";
import { ApiError, repairApi, type RepairSummary } from "@/api/client";
import NumberPagination from "@/components/NumberPagination.vue";
import AdminShell from "@/components/AdminShell.vue";
import TableSortButton from "@/components/TableSortButton.vue";

type SortField = "repairNo" | "factoryName" | "repairedQuantity" | "scrappedQuantity" | "returnedQuantity" | "warehouseReturnQuantity" | "returnDate" | "status";
const sortableColumns: Array<{ label:string; field:SortField }> = [
  { label:"返修单号", field:"repairNo" }, { label:"工厂", field:"factoryName" },
  { label:"返修数量", field:"repairedQuantity" }, { label:"报废数量", field:"scrappedQuantity" },
  { label:"返回总数量", field:"returnedQuantity" }, { label:"仓库退回总数量", field:"warehouseReturnQuantity" },
  { label:"退回时间", field:"returnDate" }, { label:"状态", field:"status" },
];
const router=useRouter();
const items=ref<RepairSummary[]>([]), loading=ref(true), error=ref("");
const archiveTarget=ref<RepairSummary|null>(null),archiving=ref(false);
const keyword=ref(""), status=ref("all"), factoryFilter=ref<string[]>([]), dateFrom=ref(""), dateTo=ref("");
const factoryMenuOpen=ref(false), page=ref(1), pageSize=10;
const sortBy=ref<SortField|"">(""), sortOrder=ref<"asc"|"desc">("asc");
const factories=ref<string[]>([]), total=ref(0), optionsError=ref("");
let requestId=0, optionsId=0, disposed=false;
const factoryLabel=computed(()=>factoryFilter.value.length===0?"全部工厂":factoryFilter.value.length===1?factoryFilter.value[0]:`已选 ${factoryFilter.value.length} 个工厂`);
const pageItems=computed(()=>items.value);
// A single combined watcher batches page reset and filter changes into one request.
watch([keyword, status, factoryFilter, dateFrom, dateTo, sortBy, sortOrder], () => { page.value=1; }, {deep:true, flush:"sync"});
watch([keyword, status, factoryFilter, dateFrom, dateTo, sortBy, sortOrder, page], () => { void load(); }, {deep:true});
async function load(){
  const id=++requestId;
  loading.value=true; error.value="";
  try {
    const result=await repairApi.listSummaries({keyword:keyword.value,status:status.value,factories:[...factoryFilter.value],returnFrom:dateFrom.value,returnTo:dateTo.value,sortBy:sortBy.value,sortOrder:sortOrder.value,page:page.value,pageSize});
    if(disposed||id!==requestId)return;
    total.value=result.total;
    const lastPage=Math.max(1,Math.ceil(result.total/pageSize));
    if(page.value>lastPage){page.value=lastPage;return;}
    items.value=result.items;
  }catch(e){if(!disposed&&id===requestId)error.value=e instanceof ApiError?e.message:"返修单加载失败";}
  finally{if(!disposed&&id===requestId)loading.value=false;}
}
async function loadFactories(){
  const id=++optionsId;
  try{const result=await repairApi.listFactoryOptions();if(disposed||id!==optionsId)return;factories.value=[...new Set(result.items)].sort((a,b)=>a.localeCompare(b,"zh-CN"));optionsError.value="";}
  catch(e){if(!disposed&&id===optionsId)optionsError.value=e instanceof ApiError?e.message:"工厂筛选选项加载失败";}
}
function search(){if(page.value!==1)page.value=1;else void load();}
function sort(field:string){const next=field as SortField;if(sortBy.value===next)sortOrder.value=sortOrder.value==="asc"?"desc":"asc";else{sortBy.value=next;sortOrder.value="asc"}page.value=1}
function reset(){keyword.value="";status.value="all";factoryFilter.value=[];dateFrom.value="";dateTo.value="";sortBy.value="";sortOrder.value="asc";page.value=1}
const n=(v:number)=>v.toLocaleString("zh-CN");
const open=(id:string)=>router.push(`/repairs/${id}`);
async function confirmArchive(){if(!archiveTarget.value||archiving.value)return;const target=archiveTarget.value;archiving.value=true;error.value="";try{await repairApi.archive(target.repairId);archiveTarget.value=null;void loadFactories();await load();}catch(e){error.value=e instanceof ApiError?e.message:"返修单归档失败"}finally{archiving.value=false}}
onMounted(()=>{void load();void loadFactories();});
onBeforeUnmount(()=>{disposed=true;requestId++;optionsId++;});
</script>

<style scoped>
.repair-filter-card{padding:0;overflow:visible}
.repair-filter-card .order-filter-form{padding-top:16px}.repair-filter-row .order-list-search-field{flex:1 1 auto}.repair-filter-row .repair-status-field{flex:0 0 116px}.repair-filter-row .repair-factory-field{flex:0 0 170px}.repair-filter-row .order-date-field{flex:0 0 142px}.repair-create-button{width:auto;min-width:106px}.repair-list-table{width:100%;min-width:1262px;table-layout:fixed}.repair-list-table th:nth-child(1){width:52px}.repair-list-table th:nth-child(2){width:calc(14.876033% - 7.735537px)}.repair-list-table th:nth-child(3){width:calc(11.570248% - 6.016529px)}.repair-list-table th:nth-child(4){width:calc(9.090909% - 4.727273px)}.repair-list-table th:nth-child(5){width:calc(9.090909% - 4.727273px)}.repair-list-table th:nth-child(6){width:calc(11.570248% - 6.016529px)}.repair-list-table th:nth-child(7){width:calc(13.223140% - 6.876033px)}.repair-list-table th:nth-child(8){width:calc(12.396694% - 6.446281px)}.repair-list-table th:nth-child(9){width:calc(9.090909% - 4.727273px)}.repair-list-table th:nth-child(10){width:calc(9.090909% - 4.727273px)}.repair-list-table th,.repair-list-table td{padding:0 14px;font-size:13px;text-align:left}.repair-list-table td{height:40px;font-weight:700}.repair-list-table .order-sequence-column,.repair-list-table .order-sequence-cell{width:52px!important;padding-right:8px!important;padding-left:8px!important;text-align:center;white-space:nowrap}.repair-list-table tbody tr:hover td{background:#e7f3ff}.repair-list-table .row-link{padding:0;background:transparent;border:0}.repair-list-table .status-badge{justify-content:center;min-width:44px;height:22px;padding:0 10px;font-size:13px}.repair-list-table .status-badge::before{display:none!important;content:none!important}.repair-list-header{height:54px;padding:0 16px}.repair-list-header h1{margin:0;font-size:18px;font-weight:800}.repair-list-footer{min-height:42px;padding:8px 14px;background:var(--surface-soft)}.repair-number-cell{font-variant-numeric:tabular-nums}.repair-archive-button{color:#d84949}.order-row-actions{gap:12px;white-space:nowrap}
</style>
