<template>
  <AdminShell>
    <article class="factory-list-page">
      <section class="order-list-filter-card factory-filter-card" aria-label="工厂筛选">
        <form class="order-filter-form" @submit.prevent="applyFilters">
          <div class="order-filter-row">
            <label class="order-list-search-field factory-search-field">
              <span class="sr-only">搜索工厂资料</span>
              <svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><circle cx="11" cy="11" r="6.5" /><path d="m16 16 4 4" /></svg>
              <input v-model="keyword" type="search" placeholder="搜索工厂名称、单位全称、联系人或电话" autocomplete="off" />
            </label>
            <label class="order-select-field"><span class="sr-only">合同资料状态</span>
              <select v-model="contractStatus"><option value="all">全部合同资料</option><option value="complete">资料完整</option><option value="incomplete">待补充</option></select>
            </label>
            <label class="order-select-field"><span class="sr-only">人员接入状态</span>
              <select v-model="accessStatus"><option value="all">全部接入状态</option><option value="connected">已接入</option><option value="unconnected">未接入</option></select>
            </label>
            <button class="order-secondary-button" type="button" @click="resetFilters">重置</button>
            <button class="order-primary-button" type="submit">搜索</button>
          </div>
        </form>
      </section>

      <section class="section-card factory-list-card" aria-labelledby="factory-list-title">
        <header class="order-list-card-header factory-list-header">
          <div class="order-list-heading"><h1 id="factory-list-title">工厂列表</h1></div>
          <button class="order-primary-button" type="button" @click="openCreate">新增工厂</button>
        </header>
        <p v-if="errorMessage" class="page-error">{{ errorMessage }}</p>
        <div class="table-scroll">
          <table class="factory-list-table data-grid-table">
            <thead><tr>
              <th scope="col">序号</th>
              <th scope="col"><TableSortButton label="编号" field="supplierNumber" :sort-by="sortBy" :sort-order="sortOrder" @sort="sortField" /></th>
              <th scope="col"><TableSortButton label="工厂名称" field="factoryName" :sort-by="sortBy" :sort-order="sortOrder" @sort="sortField" /></th>
              <th scope="col"><TableSortButton label="单位全称" field="legalName" :sort-by="sortBy" :sort-order="sortOrder" @sort="sortField" /></th>
              <th scope="col"><TableSortButton label="联系人" field="contactName" :sort-by="sortBy" :sort-order="sortOrder" @sort="sortField" /></th>
              <th scope="col"><TableSortButton label="联系电话" field="contactPhone" :sort-by="sortBy" :sort-order="sortOrder" @sort="sortField" /></th>
              <th scope="col"><TableSortButton label="合同资料" field="contractStatus" :sort-by="sortBy" :sort-order="sortOrder" @sort="sortField" /></th>
              <th scope="col"><TableSortButton label="已接入人员" field="connectedUsers" :sort-by="sortBy" :sort-order="sortOrder" @sort="sortField" /></th>
              <th scope="col">操作</th>
            </tr></thead>
            <tbody>
              <tr v-for="(factory, index) in pageFactories" :key="factory.factoryId" class="factory-data-row">
                <td class="factory-sequence">{{ (page - 1) * pageSize + index + 1 }}</td>
                <td class="factory-supplier-number">{{ factory.supplierNumber }}</td>
                <td><strong class="factory-name">{{ factory.factoryName }}</strong></td>
                <td class="factory-legal-name">{{ factory.legalName || '—' }}</td>
                <td>{{ contactNames(factory) }}</td>
                <td class="factory-phone">{{ contactPhones(factory) }}</td>
                <td><span class="factory-contract-badge" :class="factory.contractComplete ? 'is-complete' : 'is-incomplete'">{{ factory.contractComplete ? '完整' : `待补充 ${factory.missingContractFields.length} 项` }}</span></td>
                <td><button class="factory-user-count" type="button" @click="viewFactoryUsers(factory)">{{ factory.connectedUsers }} 人</button></td>
                <td><div class="factory-row-actions"><button class="text-button" type="button" @click="selectedFactory = factory">详情</button><button class="text-button" type="button" @click="openEdit(factory)">编辑</button></div></td>
              </tr>
              <tr v-if="pageFactories.length === 0"><td colspan="9"><div class="empty-state"><div><span class="empty-state-mark">0</span><strong>没有符合条件的工厂</strong><p>可以更换关键词或筛选条件后重新搜索。</p></div></div></td></tr>
            </tbody>
          </table>
        </div>
        <footer class="order-list-footer">
          <span>每页展示 10 条工厂资料。</span>
          <nav class="order-pagination" aria-label="工厂资料分页">
            <span class="order-page-total">共 {{ sortedFactories.length }} 条</span>
            <button class="order-page-button order-page-arrow" type="button" aria-label="上一页" :disabled="page <= 1" @click="page -= 1">‹</button>
            <button v-for="pageNumber in pageNumbers" :key="pageNumber" class="order-page-button" :class="{ 'is-current': pageNumber === page }" type="button" :aria-label="`第 ${pageNumber} 页`" :aria-current="pageNumber === page ? 'page' : undefined" @click="page = pageNumber">{{ pageNumber }}</button>
            <button class="order-page-button order-page-arrow" type="button" aria-label="下一页" :disabled="page >= totalPages" @click="page += 1">›</button>
          </nav>
        </footer>
      </section>
    </article>

    <div v-if="selectedFactory" class="factory-modal-backdrop" @click.self="selectedFactory = null">
      <section class="factory-modal factory-detail-modal" role="dialog" aria-modal="true" aria-labelledby="factory-detail-title">
        <div class="factory-editor-panel">
          <header class="factory-editor-header"><h2 id="factory-detail-title">详情</h2><button class="factory-modal-close" type="button" aria-label="关闭详情弹窗" @click="selectedFactory = null">×</button></header>
          <div class="factory-detail-body"><div class="factory-detail-grid">
            <div class="factory-detail-label">编号</div><div class="factory-detail-value">{{ selectedFactory.supplierNumber }}</div>
            <div class="factory-detail-label">工厂代码</div><div class="factory-detail-value">{{ selectedFactory.factoryCode }}</div>
            <div class="factory-detail-label">工厂名称</div><div class="factory-detail-value">{{ selectedFactory.factoryName }}</div>
            <div class="factory-detail-label">法定代表人</div><div class="factory-detail-value">{{ selectedFactory.legalRepresentative || '—' }}</div>
            <div class="factory-detail-label">单位全称</div><div class="factory-detail-value is-wide">{{ selectedFactory.legalName || '—' }}</div>
            <div class="factory-detail-label">联系人</div><div class="factory-detail-value">{{ contactNames(selectedFactory) }}</div>
            <div class="factory-detail-label">联系电话</div><div class="factory-detail-value">{{ contactPhones(selectedFactory) }}</div>
            <div class="factory-detail-label">单位地址</div><div class="factory-detail-value is-wide">{{ selectedFactory.address || '—' }}</div>
          </div></div>
        </div>
      </section>
    </div>

    <div v-if="editorOpen" class="factory-modal-backdrop" @click.self="closeEditor">
      <section class="factory-modal" role="dialog" aria-modal="true" aria-labelledby="factory-editor-title">
        <form class="factory-editor-panel" @submit.prevent="save">
          <header class="factory-editor-header"><h2 id="factory-editor-title">{{ editing ? '编辑' : '新增工厂' }}</h2><button class="factory-modal-close" type="button" aria-label="关闭编辑弹窗" @click="closeEditor">×</button></header>
          <div class="factory-editor-body">
            <div class="factory-form-grid">
              <label class="factory-form-label" for="supplier-number"><span>编号</span></label><div class="factory-form-control"><input id="supplier-number" v-model="form.supplierNumber" :readonly="Boolean(editing)" maxlength="32" placeholder="例如 A10" /></div>
              <label class="factory-form-label" for="factory-code"><span>工厂代码</span></label><div class="factory-form-control"><input id="factory-code" v-model="form.factoryCode" maxlength="32" placeholder="例如 XZ" /></div>
              <label class="factory-form-label" for="factory-name"><span>工厂名称</span></label><div class="factory-form-control"><input id="factory-name" v-model="form.factoryName" maxlength="100" placeholder="日常使用的工厂简称" /></div>
              <label class="factory-form-label" for="factory-legal-representative"><span>法定代表人</span></label><div class="factory-form-control"><input id="factory-legal-representative" v-model="form.legalRepresentative" maxlength="100" /></div>
              <label class="factory-form-label" for="factory-legal-name"><span>单位全称</span></label><div class="factory-form-control is-wide"><input id="factory-legal-name" v-model="form.legalName" maxlength="200" placeholder="营业执照上的单位名称" /></div>
              <template v-for="(contact, index) in form.contacts" :key="index">
                <label class="factory-form-label" :for="`contact-name-${index}`"><span>联系人</span></label><div class="factory-form-control"><input :id="`contact-name-${index}`" v-model="contact.name" placeholder="姓名" /></div>
                <label class="factory-form-label" :for="`contact-phone-${index}`"><span>联系电话</span></label><div class="factory-form-control contact-control"><input :id="`contact-phone-${index}`" v-model="contact.phone" placeholder="手机或座机" /><button class="contact-remove" type="button" aria-label="删除联系人" @click="removeContact(index)">×</button></div>
              </template>
              <div class="factory-form-spacer"></div><button class="text-button contact-add" type="button" @click="addContact">添加联系人</button>
              <label class="factory-form-label" for="factory-address"><span>单位地址</span></label><div class="factory-form-control is-wide"><input id="factory-address" v-model="form.address" maxlength="500" /></div>
            </div>
          </div>
          <footer class="factory-editor-actions"><button class="order-secondary-button" type="button" @click="closeEditor">取消</button><button class="order-primary-button" type="submit" :disabled="saving">保存</button></footer>
        </form>
      </section>
    </div>
  </AdminShell>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import { useRouter } from "vue-router";

import { ApiError, identityApi, type Factory } from "@/api/client";
import AdminShell from "@/components/AdminShell.vue";
import TableSortButton from "@/components/TableSortButton.vue";

type FactoryForm = { supplierNumber: string; factoryName: string; factoryCode: string; legalName: string; address: string; legalRepresentative: string; contacts: { name: string; phone: string }[] };

const router = useRouter();
const factories = ref<Factory[]>([]);
const keyword = ref("");
const contractStatus = ref("all");
const accessStatus = ref("all");
const sortBy = ref("");
const sortOrder = ref<"asc" | "desc">("asc");
const page = ref(1);
const pageSize = 10;
const errorMessage = ref("");
const editorOpen = ref(false);
const editing = ref<Factory | null>(null);
const selectedFactory = ref<Factory | null>(null);
const saving = ref(false);
const form = reactive<FactoryForm>(emptyForm());

const sortedFactories = computed(() => {
  if (!sortBy.value) return factories.value;
  const rows = [...factories.value];
  const direction = sortOrder.value === "asc" ? 1 : -1;
  return rows.sort((left, right) => String(sortValue(left, sortBy.value)).localeCompare(String(sortValue(right, sortBy.value)), "zh-CN", { numeric: true }) * direction);
});
const totalPages = computed(() => Math.max(1, Math.ceil(sortedFactories.value.length / pageSize)));
const pageFactories = computed(() => sortedFactories.value.slice((page.value - 1) * pageSize, page.value * pageSize));
const pageNumbers = computed(() => Array.from({ length: totalPages.value }, (_, index) => index + 1));

function emptyForm(): FactoryForm { return { supplierNumber: "", factoryName: "", factoryCode: "", legalName: "", address: "", legalRepresentative: "", contacts: [] }; }
function resetForm(value: FactoryForm) { Object.assign(form, value); }
function contactNames(factory: Factory) { return factory.contacts.map((contact) => contact.name).filter(Boolean).join("、") || "—"; }
function contactPhones(factory: Factory) { return factory.contacts.map((contact) => contact.phone).filter(Boolean).join("、") || "—"; }
function sortValue(factory: Factory, field: string) {
  if (field === "contactName") return contactNames(factory);
  if (field === "contactPhone") return contactPhones(factory);
  if (field === "contractStatus") return factory.missingContractFields.length;
  if (field === "connectedUsers") return factory.connectedUsers;
  return factory[field as "supplierNumber" | "factoryName" | "legalName"] ?? "";
}

async function load() {
  errorMessage.value = "";
  try { factories.value = (await identityApi.listFactories(keyword.value, contractStatus.value, accessStatus.value)).items; page.value = 1; }
  catch (error) { errorMessage.value = error instanceof ApiError ? error.message : "工厂资料加载失败"; }
}
async function applyFilters() { await load(); }
async function resetFilters() { keyword.value = ""; contractStatus.value = "all"; accessStatus.value = "all"; sortBy.value = ""; sortOrder.value = "asc"; await load(); }
function sortField(field: string) { if (sortBy.value === field) sortOrder.value = sortOrder.value === "asc" ? "desc" : "asc"; else { sortBy.value = field; sortOrder.value = "asc"; } page.value = 1; }
function openCreate() { editing.value = null; resetForm(emptyForm()); addContact(); editorOpen.value = true; }
function openEdit(factory: Factory) { editing.value = factory; resetForm({ supplierNumber: factory.supplierNumber, factoryName: factory.factoryName, factoryCode: factory.factoryCode, legalName: factory.legalName ?? "", address: factory.address ?? "", legalRepresentative: factory.legalRepresentative ?? "", contacts: factory.contacts.map(({ name, phone }) => ({ name, phone })) }); if (form.contacts.length === 0) addContact(); editorOpen.value = true; }
function closeEditor() { editorOpen.value = false; editing.value = null; }
function addContact() { form.contacts.push({ name: "", phone: "" }); }
function removeContact(index: number) { form.contacts.splice(index, 1); }
async function viewFactoryUsers(factory: Factory) { await router.push({ path: "/people/users", query: { factory: factory.factoryId } }); }

async function save() {
  if (!form.supplierNumber.trim() || !form.factoryName.trim() || !form.factoryCode.trim()) { errorMessage.value = "请填写供应商编号、工厂名称和工厂代码"; return; }
  saving.value = true; errorMessage.value = "";
  try {
    const payload = { factoryName: form.factoryName, factoryCode: form.factoryCode, legalName: form.legalName, address: form.address, legalRepresentative: form.legalRepresentative, contacts: form.contacts.filter((contact) => contact.name.trim() || contact.phone.trim()) };
    if (editing.value) await identityApi.updateFactory(editing.value.factoryId, { ...payload, version: editing.value.version });
    else await identityApi.createFactory({ ...payload, supplierNumber: form.supplierNumber });
    closeEditor(); await load();
  } catch (error) { errorMessage.value = error instanceof ApiError ? error.message : "工厂资料保存失败"; }
  finally { saving.value = false; }
}

onMounted(load);
</script>
