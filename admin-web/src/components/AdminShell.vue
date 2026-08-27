<template>
  <div class="app-shell" :class="{ 'is-sidebar-collapsed': sidebarCollapsed, 'is-menu-open': mobileMenuOpen }">
    <button class="mobile-overlay" type="button" aria-label="关闭导航" @click="mobileMenuOpen = false"></button>

    <aside class="sidebar" aria-label="主导航">
      <div class="app-rail">
        <div class="rail-brand"><BrandLogo /></div>
        <button
          v-for="module in modules"
          :key="module.id"
          class="rail-module"
          :class="{ 'is-active': module.id === activeModule.id }"
          type="button"
          :title="module.label"
          :aria-current="module.id === activeModule.id ? 'page' : undefined"
          @click="activateModule(module)"
        >
          <span class="rail-module-icon" aria-hidden="true">
            <svg v-if="module.id === 'dashboard'" viewBox="0 0 24 24" fill="none"><path d="M4 4h6v7H4zM14 4h6v4h-6zM14 12h6v8h-6zM4 15h6v5H4z" /></svg>
            <svg v-else-if="module.id === 'orders'" viewBox="0 0 24 24" fill="none"><path d="M6 4h12v16H6zM9 8h6M9 12h6M9 16h4" /></svg>
            <svg v-else-if="module.id === 'products'" viewBox="0 0 24 24" fill="none"><path d="M4 7.5 12 4l8 3.5-8 3.5-8-3.5ZM4 7.5V16l8 4 8-4V7.5M12 11v9" /></svg>
            <svg v-else-if="module.id === 'factory'" viewBox="0 0 24 24" fill="none"><path d="M4 20V9l6 3V8l6 3V5h4v15H4ZM8 16h1M13 16h1M18 16h1" /></svg>
            <svg v-else viewBox="0 0 24 24" fill="none"><path d="M9 11a3 3 0 1 0 0-6 3 3 0 0 0 0 6ZM3.5 19a5.5 5.5 0 0 1 11 0M16 11a2.5 2.5 0 1 0 0-5M16 14c2.6 0 4.5 1.8 4.5 4" /></svg>
          </span>
          <span>{{ module.label }}</span>
        </button>
      </div>

      <div class="page-sidebar" :id="`${activeModule.id}-page-sidebar`">
        <div class="brand-lockup"><strong class="brand-title">跟单管理</strong></div>
        <div class="sidebar-section-label">{{ activeModule.label }}</div>
        <nav class="side-nav" :aria-label="`${activeModule.label}页面`">
          <RouterLink
            v-for="item in activeModule.items"
            :key="item.route"
            class="side-nav-button"
            :to="item.route"
            @click="mobileMenuOpen = false"
          >
            <span class="nav-icon" aria-hidden="true">
              <svg v-if="item.icon === 'orders'" viewBox="0 0 24 24" fill="none"><path d="M7 4h10v3H7zM5 7h14v13H5zM8 11h8M8 15h5" /></svg>
              <svg v-else-if="item.icon === 'import'" viewBox="0 0 24 24" fill="none"><path d="M12 3v11m0 0 4-4m-4 4-4-4M5 16v4h14v-4" /></svg>
              <svg v-else-if="item.icon === 'shipment'" viewBox="0 0 24 24" fill="none"><path d="M3 6h11v10H3zM14 9h4l3 3v4h-7M7 19a2 2 0 1 0 0-4 2 2 0 0 0 0 4Zm10 0a2 2 0 1 0 0-4 2 2 0 0 0 0 4Z" /></svg>
              <svg v-else-if="item.icon === 'repair'" viewBox="0 0 24 24" fill="none"><path d="M5 4h14v16H5zM8 8h8M8 12h5M8 16h8M16 11v4m-2-2h4" /></svg>
              <svg v-else-if="activeModule.id === 'dashboard'" viewBox="0 0 24 24" fill="none"><path d="M4 4h6v7H4zM14 4h6v4h-6zM14 12h6v8h-6zM4 15h6v5H4z" /></svg>
              <svg v-else-if="activeModule.id === 'orders'" viewBox="0 0 24 24" fill="none"><path d="M6 4h12v16H6zM9 8h6M9 12h6M9 16h4" /></svg>
              <svg v-else-if="activeModule.id === 'products'" viewBox="0 0 24 24" fill="none"><path d="M4 7.5 12 4l8 3.5-8 3.5-8-3.5ZM4 7.5V16l8 4 8-4V7.5M12 11v9" /></svg>
              <svg v-else-if="activeModule.id === 'factory'" viewBox="0 0 24 24" fill="none"><path d="M4 20V9l6 3V8l6 3V5h4v15H4ZM8 16h1M13 16h1M18 16h1" /></svg>
              <svg v-else viewBox="0 0 24 24" fill="none"><path d="M9 11a3 3 0 1 0 0-6 3 3 0 0 0 0 6ZM3.5 19a5.5 5.5 0 0 1 11 0M16 11a2.5 2.5 0 1 0 0-5M16 14c2.6 0 4.5 1.8 4.5 4" /></svg>
            </span>
            <span class="nav-label">{{ item.label }}</span>
          </RouterLink>
        </nav>
      </div>
    </aside>

    <div class="main-column">
      <header class="topbar">
        <div class="topbar-left">
          <button class="icon-button mobile-menu-button" type="button" aria-label="打开导航" @click="mobileMenuOpen = true">
            <svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M4 7h16M4 12h16M4 17h16" /></svg>
          </button>
          <span class="topbar-title">{{ title ?? activeModule.label }}</span>
        </div>
        <div class="topbar-right">
          <button class="user-chip" type="button" aria-label="查看当前账号信息" :aria-expanded="accountOpen" @click.stop="accountOpen = !accountOpen">
            <span class="user-avatar">{{ userInitial }}</span>
            <span class="user-copy">
              <span class="user-name">{{ identity.currentUser?.displayName }}</span>
              <span class="user-role">{{ userRole }}</span>
            </span>
            <span class="user-menu-chevron" aria-hidden="true">
              <svg viewBox="0 0 24 24" fill="none"><path d="m8 10 4 4 4-4" /></svg>
            </span>
          </button>

          <section v-if="accountOpen" class="account-popover is-open" aria-label="账号信息">
            <div class="account-popover-header">
              <span class="user-avatar">{{ userInitial }}</span>
              <div><strong>{{ identity.currentUser?.displayName }}</strong><span>公司飞书账号</span></div>
            </div>
            <dl class="account-popover-details">
              <div><dt>飞书姓名</dt><dd>{{ identity.currentUser?.displayName }}</dd></div>
              <div><dt>管理员类型</dt><dd>{{ userRole }}</dd></div>
              <div><dt>已验证手机号</dt><dd>{{ identity.currentUser?.phoneMasked ?? '—' }}</dd></div>
            </dl>
            <button class="account-logout-button" type="button" @click="logout">退出登录</button>
          </section>
        </div>
      </header>
      <main class="page-stage"><slot /></main>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";

import BrandLogo from "@/components/BrandLogo.vue";
import { useIdentityStore } from "@/stores";

defineProps<{ title?: string }>();

type ShellModule = {
  id: "dashboard" | "orders" | "products" | "factory" | "people";
  label: string;
  route: string;
  items: { label: string; route: string; icon?: "orders" | "import" | "shipment" | "repair" }[];
};

const modules: ShellModule[] = [
  { id: "dashboard", label: "订单看板", route: "/", items: [{ label: "看板首页", route: "/" }] },
  { id: "orders", label: "订单与发货", route: "/orders", items: [{ label: "订单列表", route: "/orders", icon: "orders" }, { label: "待导入订单", route: "/orders/import", icon: "import" }, { label: "发货单列表", route: "/shipments", icon: "shipment" }, { label: "返修退回", route: "/repairs", icon: "repair" }] },
  { id: "products", label: "产品资料", route: "/products", items: [{ label: "产品列表", route: "/products" }] },
  { id: "factory", label: "工厂资料", route: "/factories", items: [{ label: "工厂列表", route: "/factories" }] },
  { id: "people", label: "人员管理", route: "/people/factory-applications", items: [{ label: "人员管理", route: "/people/factory-applications" }] },
];

const identity = useIdentityStore();
const route = useRoute();
const router = useRouter();
const mobileMenuOpen = ref(false);
const accountOpen = ref(false);
const sidebarCollapsed = ref(window.localStorage?.getItem("order-tracking-sidebar-collapsed") === "true");

const activeModule = computed(() => {
  if (route.path.startsWith("/orders") || route.path.startsWith("/shipments") || route.path.startsWith("/repairs")) return modules[1];
  if (route.path.startsWith("/products")) return modules[2];
  if (route.path.startsWith("/factories")) return modules[3];
  if (route.path.startsWith("/people")) return modules[4];
  return modules[0];
});
const userInitial = computed(() => identity.currentUser?.displayName.slice(0, 1) || "管");
const userRole = computed(() => identity.currentUser?.isSuperAdmin ? "最高管理员" : "普通管理员");

async function activateModule(module: ShellModule) {
  if (module.id === activeModule.value.id) {
    sidebarCollapsed.value = !sidebarCollapsed.value;
    window.localStorage?.setItem("order-tracking-sidebar-collapsed", String(sidebarCollapsed.value));
    return;
  }
  mobileMenuOpen.value = false;
  await router.push(module.route);
}

async function logout() {
  accountOpen.value = false;
  await identity.logout();
  await router.replace("/login");
}

watch(() => route.fullPath, () => {
  mobileMenuOpen.value = false;
  accountOpen.value = false;
});
</script>
