import { mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import ProductImage from "@/components/ProductImage.vue";

beforeEach(() => {
  Object.defineProperty(HTMLDialogElement.prototype, "showModal", { configurable: true, value: function (this: HTMLDialogElement) { this.open = true; } });
  Object.defineProperty(HTMLDialogElement.prototype, "close", { configurable: true, value: function (this: HTMLDialogElement) { this.open = false; } });
});
afterEach(() => { vi.restoreAllMocks(); document.body.style.overflow = ""; });

describe("product image preview", () => {
  it("opens only after loading and closes without propagating clicks or losing scroll styles", async () => {
    const clicked = vi.fn();
    const wrapper = mount(ProductImage, { props: { src: "/api/image?v=1", name: "童帽" }, attrs: { onClick: clicked } });
    expect(wrapper.get("button").attributes("disabled")).toBeDefined();
    await wrapper.get(".product-list-image").trigger("load");
    document.body.style.overflow = "auto";
    await wrapper.get("button").trigger("click");
    expect(wrapper.get("dialog").attributes("open")).toBeDefined();
    expect(wrapper.get("dialog img").attributes("src")).toBe("/api/image?v=1");
    expect(document.body.style.overflow).toBe("hidden");
    const tab = new KeyboardEvent("keydown", { key: "Tab", cancelable: true });
    wrapper.get("dialog").element.dispatchEvent(tab);
    expect(tab.defaultPrevented).toBe(true);
    expect(clicked).not.toHaveBeenCalled();
    await wrapper.get(".product-image-close").trigger("click");
    expect(wrapper.get("dialog").attributes("open")).toBeUndefined();
    expect(document.body.style.overflow).toBe("auto");
    for (const event of ["cancel", "click"]) {
      await wrapper.get("button").trigger("click");
      await wrapper.get("dialog").trigger(event);
      expect(wrapper.get("dialog").attributes("open")).toBeUndefined();
    }
    wrapper.unmount();
  });

  it("keeps missing/failed images disabled, closes failed previews and retries a new version", async () => {
    const wrapper = mount(ProductImage, { props: { src: null, name: "童帽" } });
    expect(wrapper.find("img").exists()).toBe(false);
    expect(wrapper.get("button").attributes("disabled")).toBeDefined();
    await wrapper.setProps({ src: "/api/image?v=1" });
    await wrapper.get(".product-list-image").trigger("error");
    expect(wrapper.find("img").exists()).toBe(false);
    await wrapper.setProps({ src: "/api/image?v=2" });
    await wrapper.get(".product-list-image").trigger("load");
    await wrapper.get("button").trigger("click");
    await wrapper.get("dialog img").trigger("error");
    expect(wrapper.get("dialog").attributes("open")).toBeUndefined();
    expect(wrapper.get("button").attributes("disabled")).toBeDefined();
    await wrapper.setProps({ src: "/api/image?v=3" });
    await wrapper.get(".product-list-image").trigger("load");
    await wrapper.get("button").trigger("click");
    wrapper.unmount();
    expect(document.body.style.overflow).toBe("");
  });
});
