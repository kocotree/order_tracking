<template>
  <AdminShell>
    <article class="order-workspace order-form-page">
      <header class="page-heading">
        <div><button class="back-link" type="button" @click="$router.back()">‹ 返回</button><h1>{{ isEdit ? '编辑草稿' : '手工新建订单' }}</h1><p>保存草稿后工厂不可见，发布前再校验完整派工。</p></div>
      </header>
      <form class="section-card order-form" @submit.prevent="save">
        <section><header class="section-heading"><h2>基本信息</h2></header><div class="form-grid">
          <label>订单编号<input v-model.trim="form.orderNo" maxlength="100" placeholder="例如 E81" /></label>
          <label>订单日期<input v-model="form.orderDate" type="date" /></label>
          <label>跟单人员<select v-model="form.tracker"><option value="" disabled>请选择</option><option v-for="item in trackers" :key="item">{{ item }}</option></select></label>
          <label>合同出货时间<input v-model="form.contractShipDate" type="date" /></label>
        </div></section>
        <section class="line-editor"><header class="section-heading"><div><h2>产品明细与工厂派工</h2><span>每条明细的派工合计在发布时必须等于订单数量</span></div><button class="order-secondary-button" type="button" @click="addLine">增加产品</button></header>
          <article v-for="(line, lineIndex) in form.lines" :key="line.key" class="product-line-card">
            <header><strong>产品明细 {{ lineIndex + 1 }}</strong><button v-if="form.lines.length > 1" type="button" @click="form.lines.splice(lineIndex, 1)">删除产品</button></header>
            <div class="line-fields">
              <label>产品规格<select v-model="line.variantId"><option value="" disabled>选择当前可用产品规格</option><option v-for="product in products" :key="product.variantId" :value="product.variantId">{{ product.skuId }} · {{ product.name }} · {{ product.propertiesValue }}</option></select></label>
              <label>订单数量<input v-model.number="line.orderQuantity" type="number" min="1" step="1" /></label>
              <div class="allocation-meter"><span>已分配 / 订单数量</span><strong :class="{ 'is-mismatch': assigned(line) !== line.orderQuantity }">{{ assigned(line) }} / {{ line.orderQuantity || 0 }}</strong></div>
            </div>
            <div class="assignment-list">
              <div v-for="(assignment, assignmentIndex) in line.assignments" :key="assignment.key" class="assignment-row">
                <label>工厂<select v-model="assignment.factoryId"><option value="" disabled>选择工厂</option><option v-for="factory in factories" :key="factory.factoryId" :value="factory.factoryId">{{ factory.factoryName }}</option></select></label>
                <label>下单数量<input v-model.number="assignment.quantity" type="number" min="1" step="1" /></label>
                <button type="button" aria-label="删除派工" @click="line.assignments.splice(assignmentIndex, 1)">删除</button>
              </div>
              <button class="inline-add-button" type="button" @click="addAssignment(line)">＋ 增加工厂派工</button>
            </div>
          </article>
        </section>
        <p v-if="errorMessage" class="page-error form-error">{{ errorMessage }}</p>
        <footer class="form-actions"><button class="order-secondary-button" type="button" @click="$router.back()">返回</button><button class="order-primary-button" type="submit" :disabled="saving">{{ saving ? '保存中…' : '保存草稿' }}</button></footer>
      </form>
    </article>
  </AdminShell>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from "vue";
import { useRoute, useRouter } from "vue-router";

import { ApiError, identityApi, orderApi, type Factory, type ProductListItem } from "@/api/client";
import AdminShell from "@/components/AdminShell.vue";

type AssignmentForm = { key: string; factoryId: string; quantity: number };
type LineForm = { key: string; variantId: string; orderQuantity: number; assignments: AssignmentForm[] };
const trackers = ["烧麦", "松子", "橄榄", "大葱", "青椒"];
const route = useRoute(); const router = useRouter(); const orderId = typeof route.params.orderId === "string" ? route.params.orderId : ""; const isEdit = Boolean(orderId);
const products = ref<ProductListItem[]>([]); const factories = ref<Factory[]>([]); const saving = ref(false); const errorMessage = ref(""); const version = ref(0);
const key = () => Math.random().toString(36).slice(2);
const form = reactive({ orderNo: "", orderDate: "", tracker: "", contractShipDate: "", lines: [{ key: key(), variantId: "", orderQuantity: 1, assignments: [] }] as LineForm[] });
const addLine = () => form.lines.push({ key: key(), variantId: "", orderQuantity: 1, assignments: [] });
const addAssignment = (line: LineForm) => line.assignments.push({ key: key(), factoryId: "", quantity: 1 });
const assigned = (line: LineForm) => line.assignments.reduce((sum, item) => sum + (Number(item.quantity) || 0), 0);

async function save() {
  errorMessage.value = "";
  if (!form.orderNo || (!isEdit && !form.orderDate) || !form.tracker || !form.contractShipDate || form.lines.some((line) => !line.variantId || !Number.isInteger(line.orderQuantity) || line.orderQuantity <= 0)) { errorMessage.value = "请完整填写基本信息、产品规格和正整数订单数量"; return; }
  if (form.lines.some((line) => line.assignments.some((item) => !item.factoryId || !Number.isInteger(item.quantity) || item.quantity <= 0))) { errorMessage.value = "派工数量只接受正整数"; return; }
  const payload = { orderNo: form.orderNo, tracker: form.tracker as "烧麦", contractShipDate: form.contractShipDate, lines: form.lines.map((line) => ({ variantId: line.variantId, orderQuantity: line.orderQuantity, assignments: line.assignments.map((item) => ({ factoryId: item.factoryId, quantity: item.quantity })) })) };
  saving.value = true;
  try {
    const result = isEdit ? await orderApi.saveDraft(orderId, { ...payload, orderDate: form.orderDate || null, version: version.value }) : await orderApi.createDraft({ ...payload, orderDate: form.orderDate });
    await router.replace(`/orders/${result.orderId}`);
  } catch (error) { errorMessage.value = error instanceof ApiError && error.status === 409 ? "数据已被其他管理员更新，请重新加载后再保存" : error instanceof ApiError ? error.message : "草稿保存失败"; }
  finally { saving.value = false; }
}

onMounted(async () => {
  const [productResult, factoryResult] = await Promise.all([identityApi.listProducts({ pageSize: 100 }), identityApi.listFactories()]); products.value = productResult.items; factories.value = factoryResult.items;
  if (!isEdit) return;
  try {
    const order = await orderApi.get(orderId); if (order.lifecycle !== "DRAFT") { errorMessage.value = "只有草稿可以编辑"; return; }
    form.orderNo = order.orderNo; form.orderDate = order.orderDate ?? ""; form.tracker = order.tracker; form.contractShipDate = order.contractShipDate; version.value = order.version;
    form.lines = order.lines.map((line) => ({ key: key(), variantId: line.variantId, orderQuantity: line.orderQuantity, assignments: line.assignments.map((item) => ({ key: key(), factoryId: item.factoryId, quantity: item.assignedQuantity })) }));
  } catch (error) { errorMessage.value = error instanceof ApiError ? error.message : "草稿加载失败"; }
});
</script>
