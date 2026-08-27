import type { Pinia } from "pinia";
import {
  createMemoryHistory,
  createRouter,
  createWebHistory,
  type Router,
} from "vue-router";

import AdminApplicationsPage from "@/pages/AdminApplicationsPage.vue";
import AdminApplyPage from "@/pages/AdminApplyPage.vue";
import AdminUsersPage from "@/pages/AdminUsersPage.vue";
import AccessStatusPage from "@/pages/AccessStatusPage.vue";
import FactoriesPage from "@/pages/FactoriesPage.vue";
import FactoryApplicationsPage from "@/pages/FactoryApplicationsPage.vue";
import FactoryUsersPage from "@/pages/FactoryUsersPage.vue";
import HomePage from "@/pages/HomePage.vue";
import LoginPage from "@/pages/LoginPage.vue";
import NotFoundPage from "@/pages/NotFoundPage.vue";
import OrderDetailPage from "@/pages/OrderDetailPage.vue";
import OrderFormPage from "@/pages/OrderFormPage.vue";
import OrdersPage from "@/pages/OrdersPage.vue";
import OrderImportPage from "@/pages/OrderImportPage.vue";
import OrderImportDetailPage from "@/pages/OrderImportDetailPage.vue";
import ProductsPage from "@/pages/ProductsPage.vue";
import RepairCreatePage from "@/pages/RepairCreatePage.vue";
import RepairDetailPage from "@/pages/RepairDetailPage.vue";
import RepairsPage from "@/pages/RepairsPage.vue";
import ShipmentDetailPage from "@/pages/ShipmentDetailPage.vue";
import ShipmentsPage from "@/pages/ShipmentsPage.vue";
import { useIdentityStore } from "@/stores";

export function createAppRouter(pinia: Pinia, initialPath?: string): Router {
  const router = createRouter({
    history: initialPath === undefined ? createWebHistory() : createMemoryHistory(),
    routes: [
      { path: "/login", name: "login", component: LoginPage, meta: { public: true } },
      { path: "/", name: "home", component: HomePage, meta: { activeAdmin: true } },
      { path: "/orders", name: "orders", component: OrdersPage },
      { path: "/orders/import", name: "order-import", component: OrderImportPage },
      { path: "/orders/import/:candidateId", name: "order-import-detail", component: OrderImportDetailPage },
      { path: "/orders/new", name: "order-new", component: OrderFormPage },
      { path: "/orders/:orderId/edit", name: "order-edit", component: OrderFormPage },
      { path: "/orders/:orderId", name: "order-detail", component: OrderDetailPage },
      { path: "/shipments", name: "shipments", component: ShipmentsPage },
      { path: "/shipments/:shipmentId", name: "shipment-detail", component: ShipmentDetailPage },
      { path: "/repairs", name: "repairs", component: RepairsPage },
      { path: "/repairs/new", name: "repair-new", component: RepairCreatePage },
      { path: "/repairs/:repairId", name: "repair-detail", component: RepairDetailPage },
      { path: "/factories", name: "factories", component: FactoriesPage },
      { path: "/products", name: "products", component: ProductsPage },
      { path: "/admin-apply", name: "admin-apply", component: AdminApplyPage },
      {
        path: "/access-status/:status(pending|rejected|disabled)",
        name: "access-status",
        component: AccessStatusPage,
      },
      {
        path: "/people/admin-applications",
        name: "admin-applications",
        component: AdminApplicationsPage,
        meta: { superAdmin: true },
      },
      {
        path: "/people/admin-users",
        name: "admin-users",
        component: AdminUsersPage,
        meta: { superAdmin: true },
      },
      {
        path: "/people/factory-applications",
        name: "factory-applications",
        component: FactoryApplicationsPage,
      },
      {
        path: "/people/users",
        name: "people-users",
        component: FactoryUsersPage,
      },
      { path: "/:pathMatch(.*)*", name: "not-found", component: NotFoundPage },
    ],
  });

  router.beforeEach(async (to) => {
    if (to.meta.public) return true;
    const identity = useIdentityStore(pinia);
    const user = await identity.loadCurrentUser();
    if (!user) return { name: "login", query: { returnTo: to.fullPath } };
    if (!user.isEnabled) {
      return to.name === "access-status" && to.params.status === "disabled"
        ? true
        : { name: "access-status", params: { status: "disabled" } };
    }
    if (user.role === null) {
      const application = await identity.loadOwnApplication();
      if (
        application?.status === "rejected" &&
        to.name === "admin-apply" &&
        to.query.reapply === "1"
      ) {
        return true;
      }
      const expectedRoute =
        application?.status === "pending" || application?.status === "rejected"
          ? { name: "access-status", params: { status: application.status } }
          : { name: "admin-apply" };
      const matchesExpected =
        to.name === expectedRoute.name &&
        (to.name !== "access-status" || to.params.status === application?.status);
      return matchesExpected ? true : expectedRoute;
    }
    if (to.name === "login" || to.name === "admin-apply" || to.name === "access-status") {
      return { name: "home" };
    }
    if (to.meta.superAdmin && !user.isSuperAdmin) return { name: "home" };
    return true;
  });
  if (initialPath !== undefined) void router.push(initialPath);
  return router;
}
