<template>
  <AdminShell>
    <section class="content-card people-card">
      <header class="content-header factory-header">
        <h1>工厂资料</h1>
        <button class="primary-button" type="button" @click="openCreate">新增工厂</button>
      </header>
      <div class="people-toolbar factory-toolbar">
        <input v-model="keyword" type="search" placeholder="搜索编号、工厂、联系人或电话" @keyup.enter="load" />
        <select v-model="contractStatus" @change="load">
          <option value="all">全部合同资料</option>
          <option value="complete">资料完整</option>
          <option value="incomplete">资料待补</option>
        </select>
        <select v-model="accessStatus" @change="load">
          <option value="all">全部接入状态</option>
          <option value="connected">已有用户</option>
          <option value="unconnected">暂无用户</option>
        </select>
        <button class="secondary-button" type="button" @click="load">查询</button>
      </div>
      <p v-if="errorMessage" class="page-error">{{ errorMessage }}</p>
      <div class="people-table-scroll">
        <table class="people-table factory-table">
          <thead>
            <tr><th>序号</th><th>供应商编号</th><th>工厂名称</th><th>单位全称</th><th>联系人</th><th>联系电话</th><th>合同资料</th><th>接入用户</th><th>操作</th></tr>
          </thead>
          <tbody>
            <tr v-for="(factory, index) in factories" :key="factory.factoryId">
              <td>{{ index + 1 }}</td>
              <td>{{ factory.supplierNumber }}</td>
              <td><strong>{{ factory.factoryName }}</strong></td>
              <td>{{ factory.legalName || '—' }}</td>
              <td>{{ factory.contacts[0]?.name || '—' }}</td>
              <td>{{ factory.contacts[0]?.phone || '—' }}</td>
              <td><span class="status-badge" :class="factory.contractComplete ? 'is-approved' : 'is-pending'">{{ factory.contractComplete ? '完整' : '待补' }}</span></td>
              <td>{{ factory.connectedUsers }}</td>
              <td><button class="text-button" type="button" @click="openEdit(factory)">编辑</button></td>
            </tr>
            <tr v-if="factories.length === 0"><td colspan="9" class="empty-cell">暂无工厂资料</td></tr>
          </tbody>
        </table>
      </div>
    </section>

    <div v-if="editorOpen" class="modal-backdrop" @click.self="closeEditor">
      <form class="modal factory-editor" @submit.prevent="save">
        <header><h2>{{ editing ? '编辑工厂' : '新增工厂' }}</h2><button type="button" aria-label="关闭" @click="closeEditor">×</button></header>
        <div class="modal-body factory-form">
          <label>供应商编号<input v-model="form.supplierNumber" :readonly="Boolean(editing)" maxlength="32" /></label>
          <label>工厂名称<input v-model="form.factoryName" maxlength="100" /></label>
          <label>工厂代码<input v-model="form.factoryCode" maxlength="32" /></label>
          <label class="wide">单位全称<input v-model="form.legalName" maxlength="200" /></label>
          <label class="wide">单位地址<input v-model="form.address" maxlength="500" /></label>
          <label>法定代表人<input v-model="form.legalRepresentative" maxlength="100" /></label>
          <section class="wide contact-editor">
            <div class="contact-heading"><strong>联系人</strong><button class="text-button" type="button" @click="addContact">添加联系人</button></div>
            <div v-for="(contact, index) in form.contacts" :key="index" class="contact-row">
              <input v-model="contact.name" aria-label="联系人姓名" placeholder="姓名" />
              <input v-model="contact.phone" aria-label="联系人电话" placeholder="联系电话" />
              <button class="text-button danger" type="button" @click="removeContact(index)">删除</button>
            </div>
            <p v-if="form.contacts.length === 0" class="form-hint">可添加一个或多个联系人。</p>
          </section>
        </div>
        <footer><button class="secondary-button" type="button" @click="closeEditor">取消</button><button class="primary-button" type="submit" :disabled="saving">保存</button></footer>
      </form>
    </div>
  </AdminShell>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from "vue";

import { ApiError, identityApi, type Factory } from "@/api/client";
import AdminShell from "@/components/AdminShell.vue";

type FactoryForm = {
  supplierNumber: string;
  factoryName: string;
  factoryCode: string;
  legalName: string;
  address: string;
  legalRepresentative: string;
  contacts: { name: string; phone: string }[];
};

const factories = ref<Factory[]>([]);
const keyword = ref("");
const contractStatus = ref("all");
const accessStatus = ref("all");
const errorMessage = ref("");
const editorOpen = ref(false);
const editing = ref<Factory | null>(null);
const saving = ref(false);
const form = reactive<FactoryForm>(emptyForm());

function emptyForm(): FactoryForm {
  return { supplierNumber: "", factoryName: "", factoryCode: "", legalName: "", address: "", legalRepresentative: "", contacts: [] };
}

function resetForm(value: FactoryForm) {
  Object.assign(form, value);
}

async function load() {
  errorMessage.value = "";
  try {
    factories.value = (await identityApi.listFactories(keyword.value, contractStatus.value, accessStatus.value)).items;
  } catch (error) {
    errorMessage.value = error instanceof ApiError ? error.message : "工厂资料加载失败";
  }
}

function openCreate() {
  editing.value = null;
  resetForm(emptyForm());
  editorOpen.value = true;
}

function openEdit(factory: Factory) {
  editing.value = factory;
  resetForm({
    supplierNumber: factory.supplierNumber,
    factoryName: factory.factoryName,
    factoryCode: factory.factoryCode,
    legalName: factory.legalName ?? "",
    address: factory.address ?? "",
    legalRepresentative: factory.legalRepresentative ?? "",
    contacts: factory.contacts.map(({ name, phone }) => ({ name, phone })),
  });
  editorOpen.value = true;
}

function closeEditor() {
  editorOpen.value = false;
  editing.value = null;
}

function addContact() {
  form.contacts.push({ name: "", phone: "" });
}

function removeContact(index: number) {
  form.contacts.splice(index, 1);
}

async function save() {
  if (!form.supplierNumber.trim() || !form.factoryName.trim() || !form.factoryCode.trim()) {
    errorMessage.value = "请填写供应商编号、工厂名称和工厂代码";
    return;
  }
  saving.value = true;
  errorMessage.value = "";
  try {
    const payload = {
      factoryName: form.factoryName,
      factoryCode: form.factoryCode,
      legalName: form.legalName,
      address: form.address,
      legalRepresentative: form.legalRepresentative,
      contacts: form.contacts,
    };
    if (editing.value) {
      await identityApi.updateFactory(editing.value.factoryId, { ...payload, version: editing.value.version });
    } else {
      await identityApi.createFactory({ ...payload, supplierNumber: form.supplierNumber });
    }
    closeEditor();
    await load();
  } catch (error) {
    errorMessage.value = error instanceof ApiError ? error.message : "工厂资料保存失败";
  } finally {
    saving.value = false;
  }
}

onMounted(load);
</script>
