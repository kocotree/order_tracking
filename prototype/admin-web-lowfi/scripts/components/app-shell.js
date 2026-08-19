const icons = {
  menu: `<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M4 7h16M4 12h16M4 17h16" stroke-width="1.8" stroke-linecap="round"/></svg>`,
  dashboard: `<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M4 4h6v7H4zM14 4h6v4h-6zM14 12h6v8h-6zM4 15h6v5H4z" stroke-width="1.6" stroke-linejoin="round"/></svg>`,
  orders: `<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M7 4h10v3H7zM5 7h14v13H5zM8 11h8M8 15h5" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>`,
  import: `<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M12 3v11m0 0 4-4m-4 4-4-4M5 16v4h14v-4" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg>`,
  shipment: `<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M3 6h11v10H3zM14 9h4l3 3v4h-7M7 19a2 2 0 1 0 0-4 2 2 0 0 0 0 4Zm10 0a2 2 0 1 0 0-4 2 2 0 0 0 0 4Z" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>`,
  repair: `<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M7 5h10l2 3-7 4-7-4 2-3Zm-2 3v9l7 4 7-4V8M12 12v9M8 15h2m4 0h2" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>`,
  products: `<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M4 7.5 12 4l8 3.5-8 3.5-8-3.5ZM4 7.5V16l8 4 8-4V7.5M12 11v9" stroke-width="1.6" stroke-linejoin="round"/></svg>`,
  factory: `<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M4 20V9l6 3V8l6 3V5h4v15H4ZM8 16h1M13 16h1M18 16h1" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>`,
  people: `<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M9 11a3 3 0 1 0 0-6 3 3 0 0 0 0 6ZM3.5 19a5.5 5.5 0 0 1 11 0M16 11a2.5 2.5 0 1 0 0-5M16 14c2.6 0 4.5 1.8 4.5 4" stroke-width="1.6" stroke-linecap="round"/></svg>`,
  bell: `<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M6.5 10a5.5 5.5 0 0 1 11 0v4l2 2H4.5l2-2v-4ZM10 19h4" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg>`,
  chevron: `<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="m8 10 4 4 4-4" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>`,
};

let toastTimer;

const railModules = [
  { id: "dashboard", label: "订单看板", icon: "dashboard", route: "/dashboard" },
  { id: "orders", label: "订单与发货", icon: "orders", route: "/orders" },
  { id: "products", label: "产品资料", icon: "products", route: "/products" },
  { id: "factory", label: "工厂资料", icon: "factory", route: "/factories" },
  { id: "people", label: "人员管理", icon: "people", route: "/people" },
];

export function escapeHTML(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function renderPopoverNotifications(notifications) {
  return notifications
    .map(
      (item) => `
        <button class="popover-notification" type="button" data-destination="${escapeHTML(item.destination)}">
          <strong>${escapeHTML(item.title)}</strong>
          <span>${escapeHTML(item.time)} · ${escapeHTML(item.description)}</span>
        </button>
      `,
    )
    .join("");
}

function renderRailModules(activeModule, savedSidebarState) {
  return railModules
    .map((module) => {
      const isActive = module.id === activeModule;
      const action = isActive
        ? `aria-controls="${escapeHTML(activeModule)}-page-sidebar" aria-expanded="${String(!savedSidebarState)}" data-toggle-current-module`
        : module.route
          ? `data-route="${escapeHTML(module.route)}"`
          : `data-pending-page="${escapeHTML(module.label)}"`;

      return `
        <button class="rail-module${isActive ? " is-active" : ""}" type="button" ${isActive ? 'aria-current="page"' : ""} title="${escapeHTML(module.label)}" ${action}>
          <span class="rail-module-icon">${icons[module.icon]}</span>
          <span>${escapeHTML(module.label)}</span>
        </button>
      `;
    })
    .join("");
}

function renderSideNavigation(items) {
  return items
    .map((item) => {
      const action = item.route
        ? `data-route="${escapeHTML(item.route)}"`
        : `data-pending-page="${escapeHTML(item.label)}"`;
      const icon = icons[item.icon] ?? icons.orders;

      return `
        <button class="side-nav-button${item.isActive ? " is-active" : ""}" type="button" ${item.isActive ? 'aria-current="page"' : ""} title="${escapeHTML(item.label)}" ${action}>
          <span class="nav-icon">${icon}</span>
          <span class="nav-label">${escapeHTML(item.label)}</span>
        </button>
      `;
    })
    .join("");
}

export function renderAppShell({
  content,
  notifications,
  activeModule = "dashboard",
  topbarTitle = "订单看板",
  sidebarSectionLabel = "订单看板",
  sideNavItems = [{ label: "看板首页", icon: "dashboard", route: "/dashboard", isActive: true }],
}) {
  const savedSidebarState = window.localStorage.getItem("order-tracking-sidebar-collapsed") === "true";

  return `
    <div class="app-shell${savedSidebarState ? " is-sidebar-collapsed" : ""}" data-app-shell>
      <button class="mobile-overlay" type="button" aria-label="关闭导航" data-close-menu></button>
      <aside class="sidebar" aria-label="主导航">
        <div class="app-rail">
          <div class="rail-brand">
            <img src="./assets/logos/logo-compact-ktk.jpg" alt="KOCOTREE" />
          </div>
          ${renderRailModules(activeModule, savedSidebarState)}
        </div>

        <div class="page-sidebar" id="${escapeHTML(activeModule)}-page-sidebar">
          <div class="brand-lockup">
            <strong class="brand-title">跟单管理</strong>
          </div>

          <div class="sidebar-section-label">${escapeHTML(sidebarSectionLabel)}</div>
          <nav class="side-nav">
            ${renderSideNavigation(sideNavItems)}
          </nav>
        </div>

      </aside>

      <div class="main-column">
        <header class="topbar">
          <div class="topbar-left">
            <button class="icon-button mobile-menu-button" type="button" aria-label="打开导航" data-open-menu>
              <span class="topbar-icon">${icons.menu}</span>
            </button>
            <span class="topbar-title">${escapeHTML(topbarTitle)}</span>
            <span class="prototype-chip">低保真原型</span>
          </div>

          <div class="topbar-right">
            <button class="icon-button" type="button" aria-label="查看通知" aria-expanded="false" data-notification-toggle>
              <span class="topbar-icon">${icons.bell}</span>
              <span class="notification-dot">${notifications.length}</span>
            </button>
            <button class="user-chip" type="button" aria-label="查看当前账号信息" aria-expanded="false" data-account-toggle>
              <span class="user-avatar">煎</span>
              <span class="user-copy">
                <span class="user-name">煎饼</span>
                <span class="user-role">最高管理员</span>
              </span>
              <span class="user-menu-chevron">${icons.chevron}</span>
            </button>

            <section class="notification-popover" aria-label="通知记录" data-notification-popover>
              <div class="popover-header">
                <strong>最近通知</strong>
                <span class="section-count">${notifications.length}</span>
              </div>
              <div class="notification-popover-list">
                ${renderPopoverNotifications(notifications)}
              </div>
            </section>

            <section class="account-popover" aria-label="账号信息" data-account-popover>
              <div class="account-popover-header">
                <span class="user-avatar">煎</span>
                <div>
                  <strong>煎饼</strong>
                  <span>公司飞书账号</span>
                </div>
              </div>
              <dl class="account-popover-details">
                <div><dt>飞书姓名</dt><dd>煎饼</dd></div>
                <div><dt>管理员类型</dt><dd>最高管理员</dd></div>
                <div><dt>已验证手机号</dt><dd>138****5122</dd></div>
              </dl>
              <button class="account-logout-button" type="button" data-account-logout>退出登录</button>
            </section>
          </div>
        </header>

        <main class="page-stage" id="main-content">
          ${content}
        </main>
      </div>

      <div class="toast" role="status" aria-live="polite" data-toast>
        <span class="toast-mark">i</span>
        <span class="toast-copy">
          <strong data-toast-title>页面待设计</strong>
          <span data-toast-message></span>
        </span>
      </div>
    </div>
  `;
}

export function showToast(title, message) {
  const toast = document.querySelector("[data-toast]");
  if (!toast) return;

  toast.querySelector("[data-toast-title]").textContent = title;
  toast.querySelector("[data-toast-message]").textContent = message;
  toast.classList.add("is-visible");

  window.clearTimeout(toastTimer);
  toastTimer = window.setTimeout(() => toast.classList.remove("is-visible"), 3200);
}

export function bindAppShell() {
  const shell = document.querySelector("[data-app-shell]");
  const currentModuleToggle = document.querySelector("[data-toggle-current-module]");
  const notificationToggle = document.querySelector("[data-notification-toggle]");
  const notificationPopover = document.querySelector("[data-notification-popover]");
  const accountToggle = document.querySelector("[data-account-toggle]");
  const accountPopover = document.querySelector("[data-account-popover]");

  const closeNotificationPopover = () => {
    notificationPopover?.classList.remove("is-open");
    notificationToggle?.setAttribute("aria-expanded", "false");
  };

  const closeAccountPopover = () => {
    accountPopover?.classList.remove("is-open");
    accountToggle?.setAttribute("aria-expanded", "false");
  };

  const applySidebarState = (isCollapsed) => {
    shell?.classList.toggle("is-sidebar-collapsed", isCollapsed);
    currentModuleToggle?.setAttribute("aria-expanded", String(!isCollapsed));
  };

  const toggleSidebarState = () => {
    const isCollapsed = !shell?.classList.contains("is-sidebar-collapsed");
    applySidebarState(isCollapsed);
    window.localStorage.setItem("order-tracking-sidebar-collapsed", String(isCollapsed));
  };

  const savedSidebarState = window.localStorage.getItem("order-tracking-sidebar-collapsed") === "true";
  applySidebarState(savedSidebarState);

  currentModuleToggle?.addEventListener("click", toggleSidebarState);

  document.querySelector("[data-open-menu]")?.addEventListener("click", () => {
    shell?.classList.add("is-menu-open");
  });

  document.querySelector("[data-close-menu]")?.addEventListener("click", () => {
    shell?.classList.remove("is-menu-open");
  });

  document.querySelectorAll("[data-route]").forEach((button) => {
    button.addEventListener("click", () => {
      shell?.classList.remove("is-menu-open");
      const route = button.dataset.route;
      if (route) window.location.hash = route;
    });
  });

  document.querySelectorAll("[data-pending-page]").forEach((button) => {
    button.addEventListener("click", () => {
      shell?.classList.remove("is-menu-open");
      const pageName = button.dataset.pendingPage;
      showToast("页面待设计", `${pageName}会在订单看板确认后单独设计。`);
    });
  });

  notificationToggle?.addEventListener("click", (event) => {
    event.stopPropagation();
    closeAccountPopover();
    const isOpen = notificationPopover?.classList.toggle("is-open") ?? false;
    notificationToggle.setAttribute("aria-expanded", String(isOpen));
  });

  accountToggle?.addEventListener("click", (event) => {
    event.stopPropagation();
    closeNotificationPopover();
    const isOpen = accountPopover?.classList.toggle("is-open") ?? false;
    accountToggle.setAttribute("aria-expanded", String(isOpen));
  });

  document.querySelector("[data-account-logout]")?.addEventListener("click", () => {
    closeAccountPopover();
    window.location.hash = "/login";
  });

  notificationPopover?.addEventListener("click", (event) => {
    const target = event.target.closest("[data-destination]");
    if (!target) return;
    showToast("目标页面待设计", `${target.dataset.destination}将在对应页面完成后开放。`);
    closeNotificationPopover();
  });

  document.addEventListener("click", (event) => {
    if (notificationPopover?.classList.contains("is-open") && !notificationPopover.contains(event.target) && !notificationToggle?.contains(event.target)) {
      closeNotificationPopover();
    }
    if (accountPopover?.classList.contains("is-open") && !accountPopover.contains(event.target) && !accountToggle?.contains(event.target)) {
      closeAccountPopover();
    }
  });

  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    closeNotificationPopover();
    closeAccountPopover();
  });
}
