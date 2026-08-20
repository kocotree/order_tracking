<template>
  <main class="auth-page" :class="modifier">
    <section class="auth-shell" aria-label="跟单看板账号访问">
      <header class="auth-brand">
        <span class="auth-brand__mark">KTK</span>
        <div>
          <strong>跟单管理系统</strong>
          <span>订单与发货协同管理</span>
        </div>
      </header>
      <slot />
    </section>
    <p class="auth-page__footer">浙江酷趣智能科技有限公司 · 内部系统</p>
  </main>
</template>

<script setup lang="ts">
defineProps<{ modifier?: string }>();
</script>
