import "./styles.css";

import { createPinia } from "pinia";
import { createApp } from "vue";

import App from "./App.vue";
import { createAppRouter } from "./router";

try {
  const pinia = createPinia();
  createApp(App).use(pinia).use(createAppRouter(pinia)).mount("#app");
} catch {
  const root = document.querySelector<HTMLDivElement>("#app");
  if (root) root.textContent = "管理端加载失败，请刷新页面后重试。";
}
