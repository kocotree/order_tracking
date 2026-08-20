import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import App from "@/App.vue";
import { createAppRouter } from "@/router";

describe("admin web entry", () => {
  it("renders the engineering baseline page through the public route", async () => {
    const router = createAppRouter("/");
    await router.isReady();

    const wrapper = mount(App, { global: { plugins: [router] } });

    expect(wrapper.text()).toContain("管理员网页工程已就绪");
    expect(wrapper.text()).toContain("尚未实现业务功能");
  });
});
