<template>
  <AdminShell title="返修退回">
    <article class="order-list-page repair-list-page">
      <section class="order-list-filter-card repair-filter-card" aria-label="返修单筛选">
        <form class="order-filter-form" @submit.prevent="page = 1">
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
        <p v-if="error" class="page-error">{{ error }}</p>
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
                <td><div class="order-row-actions"><button class="order-view-button" type="button" @click="open(item.repairId)">详情</button></div></td>
              </tr>
              <tr v-if="!loading&&!pageItems.length"><td colspan="10"><div class="empty-state"><div><span class="empty-state-mark">0</span><strong>没有符合当前条件的返修单</strong><p>可以调整返修单号、状态、工厂或退回时间范围后重新查询。</p></div></div></td></tr>
            </tbody>
          </table>
        </div>
        <footer class="order-list-footer repair-list-footer">
          <span>每页展示 10 条返修单。</span>
          <nav class="order-pagination" aria-label="返修单分页">
            <span class="order-page-total">共 {{ sortedItems.length }} 条</span>
            <button class="order-page-button order-page-arrow" type="button" :disabled="page===1" @click="page--">‹</button>
            <button v-for="number in pages" :key="number" class="order-page-button" :class="{'is-current':number===page}" type="button" @click="page=number">{{ number }}</button>
            <button class="order-page-button order-page-arrow" type="button" :disabled="page===pages" @click="page++">›</button>
          </nav>
        </footer>
      </section>
    </article>
  </AdminShell>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRouter } from "vue-router";
import { ApiError, repairApi, type Repair } from "@/api/client";
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
const items=ref<Repair[]>([]), loading=ref(true), error=ref("");
const keyword=ref(""), status=ref("all"), factoryFilter=ref<string[]>([]), dateFrom=ref(""), dateTo=ref("");
const factoryMenuOpen=ref(false), page=ref(1), pageSize=10;
const sortBy=ref<SortField|"">(""), sortOrder=ref<"asc"|"desc">("asc");
const factories=computed(()=>[...new Set(items.value.map(v=>v.factoryName))].sort((a,b)=>a.localeCompare(b,"zh-CN")));
const factoryLabel=computed(()=>factoryFilter.value.length===0?"全部工厂":factoryFilter.value.length===1?factoryFilter.value[0]:`已选 ${factoryFilter.value.length} 个工厂`);
const filtered=computed(()=>{const k=keyword.value.trim().toLocaleLowerCase("zh-CN");return items.value.filter(v=>(!k||`${v.repairNo} ${v.factoryName}`.toLocaleLowerCase("zh-CN").includes(k))&&(status.value==="all"||v.status===status.value)&&(!factoryFilter.value.length||factoryFilter.value.includes(v.factoryName))&&(!dateFrom.value||v.returnDate>=dateFrom.value)&&(!dateTo.value||v.returnDate<=dateTo.value));});
const sortedItems=computed(()=>{const values=[...filtered.value];if(!sortBy.value)return values;return values.sort((a,b)=>{const av=a[sortBy.value as SortField],bv=b[sortBy.value as SortField];const result=typeof av==="number"&&typeof bv==="number"?av-bv:String(av).localeCompare(String(bv),"zh-CN",{numeric:true});return sortOrder.value==="asc"?result:-result;});});
const pages=computed(()=>Math.max(1,Math.ceil(sortedItems.value.length/pageSize)));
const pageItems=computed(()=>sortedItems.value.slice((page.value-1)*pageSize,page.value*pageSize));
watch(sortedItems,()=>{if(page.value>pages.value)page.value=pages.value});
function sort(field:string){const next=field as SortField;if(sortBy.value===next)sortOrder.value=sortOrder.value==="asc"?"desc":"asc";else{sortBy.value=next;sortOrder.value="asc"}page.value=1}
function reset(){keyword.value="";status.value="all";factoryFilter.value=[];dateFrom.value="";dateTo.value="";sortBy.value="";sortOrder.value="asc";page.value=1}
const n=(v:number)=>v.toLocaleString("zh-CN");
const open=(id:string)=>router.push(`/repairs/${id}`);
onMounted(async()=>{try{items.value=(await repairApi.list({pageSize:100})).items}catch(e){error.value=e instanceof ApiError?e.message:"返修单加载失败"}finally{loading.value=false}});
</script>

<style scoped>
.repair-filter-card{padding:0;overflow:visible}
.repair-filter-card .order-filter-form{padding-top:16px}.repair-filter-row .order-list-search-field{flex:1 1 auto}.repair-filter-row .repair-status-field{flex:0 0 116px}.repair-filter-row .repair-factory-field{flex:0 0 170px}.repair-filter-row .order-date-field{flex:0 0 142px}.repair-create-button{width:auto;min-width:106px}.repair-list-table{width:100%;min-width:1158px;table-layout:fixed}.repair-list-table th:nth-child(1){width:52px}.repair-list-table th:nth-child(2){width:178px}.repair-list-table th:nth-child(3){width:128px}.repair-list-table th:nth-child(4),.repair-list-table th:nth-child(5),.repair-list-table th:nth-child(6),.repair-list-table th:nth-child(7){width:126px}.repair-list-table th:nth-child(8){width:152px}.repair-list-table th:nth-child(9){width:104px}.repair-list-table th:nth-child(10){width:104px}.repair-list-table th,.repair-list-table td{padding:0 14px;font-size:13px;text-align:left}.repair-list-table td{height:40px;font-weight:700}.repair-list-table .order-sequence-column,.repair-list-table .order-sequence-cell{width:52px!important;padding-right:8px!important;padding-left:8px!important;text-align:center;white-space:nowrap}.repair-list-table tbody tr:hover td{background:#e7f3ff}.repair-list-table .row-link{padding:0;background:transparent;border:0}.repair-list-table .status-badge{justify-content:center;min-width:44px;height:22px;padding:0 10px;font-size:13px}.repair-list-table .status-badge::before{display:none!important;content:none!important}.repair-list-header{height:54px;padding:0 16px}.repair-list-header h1{margin:0;font-size:18px;font-weight:800}.repair-list-footer{min-height:42px;padding:8px 14px;background:var(--surface-soft)}.repair-number-cell{font-variant-numeric:tabular-nums}
</style>
