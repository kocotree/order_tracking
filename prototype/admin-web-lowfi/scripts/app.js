import { dashboardData } from "./mock-data.js";
import { ensureInitialRoute, startRouter } from "./router.js";
import { bindAppShell, renderAppShell, showToast } from "./components/app-shell.js";
import { bindDashboardPage, renderDashboardPage } from "./pages/dashboard.js";
import { bindOrderListPage, renderOrderListPage } from "./pages/order-list.js";
import { bindOrderDetailPage, renderOrderDetailPage } from "./pages/order-detail.js";
import { bindPendingImportListPage, renderPendingImportListPage } from "./pages/pending-import-list.js";
import { bindPendingImportDetailPage, renderPendingImportDetailPage } from "./pages/pending-import-detail.js";

const appRoot = document.querySelector("#app");

function renderRoute(route) {
  if (!appRoot) return;

  const orderDetailMatch = route.match(/^\/orders\/(.+)$/);
  const pendingImportDetailMatch = route.match(/^\/pending-imports\/(.+)$/);

  const routes = {
    "/dashboard": {
      activeModule: "dashboard",
      topbarTitle: "订单看板",
      sidebarSectionLabel: "订单看板",
      sideNavItems: [{ label: "看板首页", icon: "dashboard", route: "/dashboard", isActive: true }],
      content: renderDashboardPage,
      bind: bindDashboardPage,
      title: "订单看板｜跟单看板低保真原型",
    },
    "/orders": {
      activeModule: "orders",
      topbarTitle: "订单列表",
      sidebarSectionLabel: "订单与发货",
      sideNavItems: [
        { label: "订单列表", icon: "orders", route: "/orders", isActive: true },
        { label: "待导入订单", icon: "import", route: "/pending-imports" },
        { label: "发货单列表", icon: "shipment" },
      ],
      content: renderOrderListPage,
      bind: bindOrderListPage,
      title: "订单列表｜跟单看板低保真原型",
    },
    "/pending-imports": {
      activeModule: "orders",
      topbarTitle: "待导入订单",
      sidebarSectionLabel: "订单与发货",
      sideNavItems: [
        { label: "订单列表", icon: "orders", route: "/orders" },
        { label: "待导入订单", icon: "import", route: "/pending-imports", isActive: true },
        { label: "发货单列表", icon: "shipment" },
      ],
      content: renderPendingImportListPage,
      bind: bindPendingImportListPage,
      title: "待导入订单｜跟单看板低保真原型",
    },
  };
  const orderNo = orderDetailMatch ? decodeURIComponent(orderDetailMatch[1]) : "";
  const detailPage = orderDetailMatch
    ? {
        activeModule: "orders",
        topbarTitle: `订单详情 · ${orderNo}`,
        sidebarSectionLabel: "订单与发货",
        sideNavItems: [
          { label: "订单列表", icon: "orders", route: "/orders", isActive: true },
          { label: "待导入订单", icon: "import", route: "/pending-imports" },
          { label: "发货单列表", icon: "shipment" },
        ],
        content: () => renderOrderDetailPage(orderNo),
        bind: () => bindOrderDetailPage(orderNo),
        title: `${orderNo} 订单详情｜跟单看板低保真原型`,
      }
    : null;
  const pendingImportOrderNo = pendingImportDetailMatch ? decodeURIComponent(pendingImportDetailMatch[1]) : "";
  const pendingImportDetailPage = pendingImportDetailMatch
    ? {
        activeModule: "orders",
        topbarTitle: `待导入订单详情 · ${pendingImportOrderNo}`,
        sidebarSectionLabel: "订单与发货",
        sideNavItems: [
          { label: "订单列表", icon: "orders", route: "/orders" },
          { label: "待导入订单", icon: "import", route: "/pending-imports", isActive: true },
          { label: "发货单列表", icon: "shipment" },
        ],
        content: () => renderPendingImportDetailPage(pendingImportOrderNo),
        bind: () => bindPendingImportDetailPage(pendingImportOrderNo),
        title: `${pendingImportOrderNo} 待导入订单详情｜跟单看板低保真原型`,
      }
    : null;
  const page = pendingImportDetailPage ?? detailPage ?? routes[route] ?? routes["/dashboard"];

  appRoot.innerHTML = renderAppShell({
    content: page.content(),
    notifications: dashboardData.notifications,
    activeModule: page.activeModule,
    topbarTitle: page.topbarTitle,
    sidebarSectionLabel: page.sidebarSectionLabel,
    sideNavItems: page.sideNavItems,
  });

  bindAppShell();
  page.bind();
  document.title = page.title;

  if (!routes[route] && !detailPage && !pendingImportDetailPage) {
    showToast("页面待设计", "当前地址尚未开放，已返回订单看板。");
  }
}

ensureInitialRoute();
startRouter(renderRoute);
