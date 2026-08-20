import {
  createMemoryHistory,
  createRouter,
  createWebHistory,
  type Router,
} from "vue-router";

import BaselinePage from "@/pages/BaselinePage.vue";
import NotFoundPage from "@/pages/NotFoundPage.vue";

export function createAppRouter(initialPath?: string): Router {
  const router = createRouter({
    history: initialPath === undefined ? createWebHistory() : createMemoryHistory(),
    routes: [
      { path: "/", name: "baseline", component: BaselinePage },
      { path: "/:pathMatch(.*)*", name: "not-found", component: NotFoundPage },
    ],
  });
  if (initialPath !== undefined) void router.push(initialPath);
  return router;
}
