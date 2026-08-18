import { dashboardData } from "./mock-data.js";
import { ensureInitialRoute, startRouter } from "./router.js";
import { bindAppShell, renderAppShell, showToast } from "./components/app-shell.js";
import { bindDashboardPage, renderDashboardPage } from "./pages/dashboard.js";
import { bindOrderListPage, renderOrderListPage } from "./pages/order-list.js";
import { bindOrderDetailPage, renderOrderDetailPage } from "./pages/order-detail.js";
import { bindPendingImportListPage, renderPendingImportListPage } from "./pages/pending-import-list.js";
import { bindPendingImportDetailPage, renderPendingImportDetailPage } from "./pages/pending-import-detail.js";
import { bindShipmentListPage, renderShipmentListPage } from "./pages/shipment-list.js";
import { bindShipmentDetailPage, renderShipmentDetailPage } from "./pages/shipment-detail.js";
import { bindRepairListPage, renderRepairListPage } from "./pages/repair-list.js";
import { bindRepairCreatePage, renderRepairCreatePage } from "./pages/repair-create.js";
import { bindRepairDetailPage, renderRepairDetailPage } from "./pages/repair-detail.js";
import { bindProductListPage, renderProductListPage } from "./pages/product-list.js";
import { bindFactoryListPage, renderFactoryListPage } from "./pages/factory-list.js";
import { bindPeopleManagementPage, renderPeopleManagementPage } from "./pages/people-management.js";

const appRoot = document.querySelector("#app");

function renderRoute(route) {
  if (!appRoot) return;

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
      title: "订单看板｜跟单看板低保真原型",
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
      title: "订单列表｜跟单看板低保真原型",
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
      title: "待导入订单｜跟单看板低保真原型",
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
      title: "发货单列表｜跟单看板低保真原型",
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
      title: "返修退回｜跟单看板低保真原型",
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
      title: "新建返修单｜跟单看板低保真原型",
    },
    "/products": {
      activeModule: "products",
      topbarTitle: "产品资料",
      sidebarSectionLabel: "产品资料",
      sideNavItems: [{ label: "产品列表", icon: "products", route: "/products", isActive: true }],
      content: renderProductListPage,
      bind: bindProductListPage,
      title: "产品资料｜跟单看板低保真原型",
    },
    "/factories": {
      activeModule: "factory",
      topbarTitle: "工厂资料",
      sidebarSectionLabel: "工厂资料",
      sideNavItems: [{ label: "工厂列表", icon: "factory", route: "/factories", isActive: true }],
      content: renderFactoryListPage,
      bind: bindFactoryListPage,
      title: "工厂资料｜跟单看板低保真原型",
    },
    "/people": {
      activeModule: "people",
      topbarTitle: "人员管理",
      sidebarSectionLabel: "人员管理",
      sideNavItems: [{ label: "人员管理", icon: "people", route: "/people", isActive: true }],
      content: renderPeopleManagementPage,
      bind: bindPeopleManagementPage,
      title: "人员管理｜跟单看板低保真原型",
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
          { label: "发货单列表", icon: "shipment", route: "/shipments" },
          { label: "返修退回", icon: "repair", route: "/repairs" },
        ],
        content: () => renderPendingImportDetailPage(pendingImportOrderNo),
        bind: () => bindPendingImportDetailPage(pendingImportOrderNo),
        title: `${pendingImportOrderNo} 待导入订单详情｜跟单看板低保真原型`,
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
        title: `${shipmentNo} 发货单详情｜跟单看板低保真原型`,
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
        title: `${repairNo} 返修详情｜跟单看板低保真原型`,
      }
    : null;
  const page = repairDetailPage ?? shipmentDetailPage ?? pendingImportDetailPage ?? detailPage ?? routes[route] ?? routes["/dashboard"];

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

  if (!routes[route] && !detailPage && !pendingImportDetailPage && !shipmentDetailPage && !repairDetailPage) {
    showToast("页面待设计", "当前地址尚未开放，已返回订单看板。");
  }
}

ensureInitialRoute();
startRouter(renderRoute);
