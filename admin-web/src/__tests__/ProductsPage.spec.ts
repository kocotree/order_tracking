import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, expect, it, vi } from "vitest";

import { identityApi } from "@/api/client";
import ProductImage from "@/components/ProductImage.vue";
import ProductsPage from "@/pages/ProductsPage.vue";

afterEach(() => vi.restoreAllMocks());

it("keeps each SKU thumbnail and preview bound to its own versioned image", async () => {
  const items = ["blue-s", "blue-m", "red-s", "red-m"].map((sku) => ({
    variantId: sku, iId: "STYLE", skuId: sku, name: "测试帽", category: "童帽春夏",
    propertiesValue: sku, imageAvailable: true,
    imageUrl: `/api/v1/admin/products/variants/${sku}/image?v=${sku}`,
  }));
  vi.spyOn(identityApi, "listProducts").mockResolvedValue({ items, total: 4, page: 1, pageSize: 10 });
  const wrapper = mount(ProductsPage, {
    global: { stubs: { AdminShell: { template: "<div><slot /></div>" } } },
  });
  await flushPromises();
  expect(wrapper.findAllComponents(ProductImage).map((image) => image.props("src")))
    .toEqual(items.map((item) => item.imageUrl));
  expect(items[0]!.imageUrl).not.toBe(items[1]!.imageUrl);
  await wrapper.findAll(".product-list-image")[0]!.trigger("error");
  expect(wrapper.findAllComponents(ProductImage)[1]!.find("img").exists()).toBe(true);
  expect(wrapper.findAllComponents(ProductImage)[2]!.props("src")).toContain("/red-s/");
  wrapper.unmount();
});
