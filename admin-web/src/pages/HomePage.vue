<template>
  <AdminShell>
    <article class="order-workspace dashboard-page">
      <header class="page-heading">
        <div><p class="page-kicker">订单看板</p><h1>跟单进度概览</h1></div>
        <RouterLink class="order-primary-button" to="/orders">查看全部订单</RouterLink>
      </header>

      <section class="dashboard-stats" aria-label="订单统计">
        <article><span>已逾期订单</span><strong>{{ dashboard?.overdueOrders ?? 0 }}</strong><small>需要优先跟进</small></article>
        <article><span>待导入订单</span><strong>{{ dashboard?.pendingImportOrders ?? 0 }}</strong><small>S05 接入后显示</small></article>
        <article><span>今日发货记录</span><strong>{{ dashboard?.todayShipments ?? 0 }}</strong><small>S07 接入后显示</small></article>
      </section>

      <section class="section-card dashboard-orders">
        <header class="section-heading"><h2>最近订单</h2><span>按更新时间展示</span></header>
        <p v-if="loading" class="page-state">正在加载订单…</p>
        <p v-else-if="errorMessage" class="page-error">{{ errorMessage }}</p>
        <div v-else-if="dashboard?.recentOrders.length" class="table-scroll">
          <table class="order-table">
            <thead><tr><th>订单编号</th><th>产品摘要</th><th>跟单人员</th><th>合同出货时间</th><th>订单数量</th><th>未发数量</th><th>状态</th></tr></thead>
            <tbody>
              <tr v-for="item in dashboard.recentOrders" :key="item.orderId" @click="$router.push(`/orders/${item.orderId}`)">
                <td><strong>{{ item.orderNo }}</strong></td>
                <td>{{ productSummary(item) }}</td>
                <td>{{ item.tracker }}</td>
                <td>{{ item.contractShipDate }}</td>
                <td>{{ number(item.totalQuantity) }}</td>
                <td>{{ number(item.pendingQuantity) }}</td>
                <td><span class="order-status" :data-status="item.displayStatus">{{ item.displayStatus }}</span></td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-else class="empty-state"><strong>暂无正式订单</strong><p>发布草稿后，最近订单会显示在这里。</p></div>
      </section>

      <section class="section-card dashboard-notices">
        <header class="section-heading"><h2>最近通知</h2></header>
        <div class="empty-state"><strong>暂无通知</strong><p>S11 接入通知后显示真实消息。</p></div>
      </section>
    </article>
  </AdminShell>
</template>

<script setup lang="ts">
import { onMounted, ref } from "vue";

import { ApiError, orderApi, type DashboardOrders, type Order } from "@/api/client";
import AdminShell from "@/components/AdminShell.vue";

const dashboard = ref<DashboardOrders | null>(null);
const loading = ref(true);
const errorMessage = ref("");
const number = (value: number) => value.toLocaleString("zh-CN");
const productSummary = (order: Order) => order.lines.map((item) => item.productName).join("、") || "—";

onMounted(async () => {
  try {
    dashboard.value = await orderApi.dashboard();
  } catch (error) {
    errorMessage.value = error instanceof ApiError ? error.message : "订单看板加载失败";
  } finally {
    loading.value = false;
  }
});
</script>
