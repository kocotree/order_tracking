import { dashboardData, notificationData } from "./mock-data.js?v=20260827-s11-notifications";
import { ensureInitialRoute, startRouter } from "./router.js?v=20260827-s11-return-context";
import { bindAppShell, renderAppShell, showToast } from "./components/app-shell.js?v=20260827-s11-return-context";
import { bindDashboardPage, renderDashboardPage } from "./pages/dashboard.js?v=20260827-s11-return-context";
import { bindNotificationListPage, renderNotificationListPage } from "./pages/notification-list.js?v=20260827-s11-return-context";
import { bindOrderListPage, renderOrderListPage } from "./pages/order-list.js?v=20260827-s09";
import { bindOrderDetailPage, renderOrderDetailPage } from "./pages/order-detail.js?v=20260827-s11-return-context";
import { bindPendingImportListPage, renderPendingImportListPage } from "./pages/pending-import-list.js?v=20260827-s09";
import { bindPendingImportDetailPage, renderPendingImportDetailPage } from "./pages/pending-import-detail.js?v=20260827-s09";
import { bindShipmentListPage, renderShipmentListPage } from "./pages/shipment-list.js?v=20260827-s09";
import { bindShipmentDetailPage, renderShipmentDetailPage } from "./pages/shipment-detail.js?v=20260827-s11-return-context";
import { bindRepairListPage, renderRepairListPage } from "./pages/repair-list.js?v=20260827-s09";
import { bindRepairCreatePage, renderRepairCreatePage } from "./pages/repair-create.js?v=20260827-s09";
import { bindRepairDetailPage, renderRepairDetailPage } from "./pages/repair-detail.js?v=20260827-s11-return-context";
import { bindProductListPage, renderProductListPage } from "./pages/product-list.js?v=20260827-s09";
import { bindFactoryListPage, renderFactoryListPage } from "./pages/factory-list.js?v=20260827-s09";
import { bindPeopleManagementPage, renderPeopleManagementPage } from "./pages/people-management.js?v=20260827-s09";
import {
  bindAccessStatusPage,
  bindAdminApplyPage,
  bindLoginPage,
  renderAccessStatusPage,
  renderAdminApplyPage,
  renderLoginPage,
} from "./pages/auth.js?v=20260827-s09";

const appRoot = document.querySelector("#app");

function renderRoute(route) {
  if (!appRoot) return;

  const accessStatusMatch = route.match(/^\/access-status\/(pending|rejected|disabled)$/);
  const standalonePage = route === "/login"
    ? {
        content: renderLoginPage,
        bind: bindLoginPage,
        title: "登录｜跟单管理系统低保真原型",
      }
    : route === "/admin-apply"
      ? {
          content: renderAdminApplyPage,
          bind: bindAdminApplyPage,
          title: "管理员申请｜跟单管理系统低保真原型",
        }
      : accessStatusMatch
        ? {
            content: () => renderAccessStatusPage(accessStatusMatch[1]),
            bind: () => bindAccessStatusPage(accessStatusMatch[1]),
            title: "访问状态｜跟单管理系统低保真原型",
          }
        : null;

  if (standalonePage) {
    appRoot.innerHTML = standalonePage.content();
    standalonePage.bind();
    document.title = standalonePage.title;
    return;
  }

  const orderDetailMatch = route.match(/^\/orders\/(.+)$/);
  const pendingImportDetailMatch = route.match(/^\/pending-imports\/(.+)$/);
  const shipmentDetailMatch = route.match(/^\/shipments\/(.+)$/);
  const repairDetailMatch = route.match(/^\/repairs\/(.+)$/);

  const routes = {
    "/dashboard": {
      activeModule: "dashboard",
      topbarTitle: "订单看板",
      sidebarSectionLabel: "订单看板",
      sideNavItems: [{ label: "看板首页", icon: "dashboard", route: "/dashboard", isActive: true }],
      content: renderDashboardPage,
      bind: bindDashboardPage,
      title: "订单看板｜跟单管理系统低保真原型",
    },
    "/notifications": {
      activeModule: "dashboard",
      topbarTitle: "通知记录",
      sidebarSectionLabel: "订单看板",
      sideNavItems: [{ label: "看板首页", icon: "dashboard", route: "/dashboard" }],
      content: renderNotificationListPage,
      bind: bindNotificationListPage,
      title: "通知记录｜跟单管理系统低保真原型",
    },
    "/orders": {
      activeModule: "orders",
      topbarTitle: "订单列表",
      sidebarSectionLabel: "订单与发货",
      sideNavItems: [
        { label: "订单列表", icon: "orders", route: "/orders", isActive: true },
        { label: "待导入订单", icon: "import", route: "/pending-imports" },
        { label: "发货单列表", icon: "shipment", route: "/shipments" },
        { label: "返修退回", icon: "repair", route: "/repairs" },
      ],
      content: renderOrderListPage,
      bind: bindOrderListPage,
      title: "订单列表｜跟单管理系统低保真原型",
    },
    "/pending-imports": {
      activeModule: "orders",
      topbarTitle: "待导入订单",
      sidebarSectionLabel: "订单与发货",
      sideNavItems: [
        { label: "订单列表", icon: "orders", route: "/orders" },
        { label: "待导入订单", icon: "import", route: "/pending-imports", isActive: true },
        { label: "发货单列表", icon: "shipment", route: "/shipments" },
        { label: "返修退回", icon: "repair", route: "/repairs" },
      ],
      content: renderPendingImportListPage,
      bind: bindPendingImportListPage,
      title: "待导入订单｜跟单管理系统低保真原型",
    },
    "/shipments": {
      activeModule: "orders",
      topbarTitle: "发货单列表",
      sidebarSectionLabel: "订单与发货",
      sideNavItems: [
        { label: "订单列表", icon: "orders", route: "/orders" },
        { label: "待导入订单", icon: "import", route: "/pending-imports" },
        { label: "发货单列表", icon: "shipment", route: "/shipments", isActive: true },
        { label: "返修退回", icon: "repair", route: "/repairs" },
      ],
      content: renderShipmentListPage,
      bind: bindShipmentListPage,
      title: "发货单列表｜跟单管理系统低保真原型",
    },
    "/repairs": {
      activeModule: "orders",
      topbarTitle: "返修退回",
      sidebarSectionLabel: "订单与发货",
      sideNavItems: [
        { label: "订单列表", icon: "orders", route: "/orders" },
        { label: "待导入订单", icon: "import", route: "/pending-imports" },
        { label: "发货单列表", icon: "shipment", route: "/shipments" },
        { label: "返修退回", icon: "repair", route: "/repairs", isActive: true },
      ],
      content: renderRepairListPage,
      bind: bindRepairListPage,
      title: "返修退回｜跟单管理系统低保真原型",
    },
    "/repairs/new": {
      activeModule: "orders",
      topbarTitle: "新建返修单",
      sidebarSectionLabel: "订单与发货",
      sideNavItems: [
        { label: "订单列表", icon: "orders", route: "/orders" },
        { label: "待导入订单", icon: "import", route: "/pending-imports" },
        { label: "发货单列表", icon: "shipment", route: "/shipments" },
        { label: "返修退回", icon: "repair", route: "/repairs", isActive: true },
      ],
      content: renderRepairCreatePage,
      bind: bindRepairCreatePage,
      title: "新建返修单｜跟单管理系统低保真原型",
    },
    "/products": {
      activeModule: "products",
      topbarTitle: "产品资料",
      sidebarSectionLabel: "产品资料",
      sideNavItems: [{ label: "产品列表", icon: "products", route: "/products", isActive: true }],
      content: renderProductListPage,
      bind: bindProductListPage,
      title: "产品资料｜跟单管理系统低保真原型",
    },
    "/factories": {
      activeModule: "factory",
      topbarTitle: "工厂资料",
      sidebarSectionLabel: "工厂资料",
      sideNavItems: [{ label: "工厂列表", icon: "factory", route: "/factories", isActive: true }],
      content: renderFactoryListPage,
      bind: bindFactoryListPage,
      title: "工厂资料｜跟单管理系统低保真原型",
    },
    "/people": {
      activeModule: "people",
      topbarTitle: "人员管理",
      sidebarSectionLabel: "人员管理",
      sideNavItems: [{ label: "人员管理", icon: "people", route: "/people", isActive: true }],
      content: renderPeopleManagementPage,
      bind: bindPeopleManagementPage,
      title: "人员管理｜跟单管理系统低保真原型",
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
          { label: "发货单列表", icon: "shipment", route: "/shipments" },
          { label: "返修退回", icon: "repair", route: "/repairs" },
        ],
        content: () => renderOrderDetailPage(orderNo),
        bind: () => bindOrderDetailPage(orderNo),
        title: `${orderNo} 订单详情｜跟单管理系统低保真原型`,
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
          { label: "发货单列表", icon: "shipment", route: "/shipments" },
          { label: "返修退回", icon: "repair", route: "/repairs" },
        ],
        content: () => renderPendingImportDetailPage(pendingImportOrderNo),
        bind: () => bindPendingImportDetailPage(pendingImportOrderNo),
        title: `${pendingImportOrderNo} 待导入订单详情｜跟单管理系统低保真原型`,
      }
    : null;
  const shipmentNo = shipmentDetailMatch ? decodeURIComponent(shipmentDetailMatch[1]) : "";
  const shipmentDetailPage = shipmentDetailMatch
    ? {
        activeModule: "orders",
        topbarTitle: `发货单详情 · ${shipmentNo}`,
        sidebarSectionLabel: "订单与发货",
        sideNavItems: [
          { label: "订单列表", icon: "orders", route: "/orders" },
          { label: "待导入订单", icon: "import", route: "/pending-imports" },
          { label: "发货单列表", icon: "shipment", route: "/shipments", isActive: true },
          { label: "返修退回", icon: "repair", route: "/repairs" },
        ],
        content: () => renderShipmentDetailPage(shipmentNo),
        bind: () => bindShipmentDetailPage(shipmentNo),
        title: `${shipmentNo} 发货单详情｜跟单管理系统低保真原型`,
      }
    : null;
  const repairNo = repairDetailMatch ? decodeURIComponent(repairDetailMatch[1]) : "";
  const repairDetailPage = repairDetailMatch && repairNo !== "new"
    ? {
        activeModule: "orders",
        topbarTitle: `返修详情 · ${repairNo}`,
        sidebarSectionLabel: "订单与发货",
        sideNavItems: [
          { label: "订单列表", icon: "orders", route: "/orders" },
          { label: "待导入订单", icon: "import", route: "/pending-imports" },
          { label: "发货单列表", icon: "shipment", route: "/shipments" },
          { label: "返修退回", icon: "repair", route: "/repairs", isActive: true },
        ],
        content: () => renderRepairDetailPage(repairNo),
        bind: () => bindRepairDetailPage(repairNo),
        title: `${repairNo} 返修详情｜跟单管理系统低保真原型`,
      }
    : null;
  const page = repairDetailPage ?? shipmentDetailPage ?? pendingImportDetailPage ?? detailPage ?? routes[route] ?? routes["/dashboard"];

  appRoot.innerHTML = renderAppShell({
    content: page.content(),
    notifications: notificationData,
    activeModule: page.activeModule,
    topbarTitle: page.topbarTitle,
    sidebarSectionLabel: page.sidebarSectionLabel,
    sideNavItems: page.sideNavItems,
  });

  bindAppShell(notificationData);
  page.bind();
  document.title = page.title;

  if (!routes[route] && !detailPage && !pendingImportDetailPage && !shipmentDetailPage && !repairDetailPage) {
    showToast("页面待设计", "当前地址尚未开放，已返回订单看板。");
  }
}

ensureInitialRoute();
startRouter(renderRoute);
