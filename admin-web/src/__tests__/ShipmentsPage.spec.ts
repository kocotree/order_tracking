import { mount, flushPromises } from "@vue/test-utils";
import { createRouter, createMemoryHistory } from "vue-router";
import { afterEach, expect, it, vi } from "vitest";
import ShipmentsPage from "@/pages/ShipmentsPage.vue";
import { shipmentApi } from "@/api/client";
afterEach(() => vi.restoreAllMocks());
it("filters dashboard dates and allows resetting them", async () => {
  vi.spyOn(shipmentApi, "list").mockResolvedValue({ items: [
    { shipmentId: "a", shipmentNo: "TODAY", businessDate: "2026-09-05", lines: [], totalQuantity: 1 },
    { shipmentId: "b", shipmentNo: "YESTERDAY", businessDate: "2026-09-04", lines: [], totalQuantity: 1 },
  ] } as never);
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: "/shipments", component: ShipmentsPage }] });
  await router.push("/shipments?dateFrom=2026-09-05&dateTo=2026-09-05");
  const wrapper = mount(ShipmentsPage, { global: { plugins: [router], stubs: { AdminShell: { template: "<div><slot/></div>" } } } });
  await flushPromises();
  expect(wrapper.text()).toContain("TODAY"); expect(wrapper.text()).not.toContain("YESTERDAY");
  await wrapper.get(".order-secondary-button").trigger("click");
  expect(wrapper.text()).toContain("YESTERDAY");
  wrapper.unmount();
});
