import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import NumberPagination from "@/components/NumberPagination.vue";

describe("number pagination", () => {
  it.each([
    [0, 1, "1"], [70, 4, "1 2 3 4 5 6 7"],
    [200, 1, "1 2 3 4 5 … 20"], [200, 4, "1 2 3 4 5 … 20"],
    [200, 10, "1 … 9 10 11 … 20"], [200, 17, "1 … 16 17 18 19 20"],
  ])("renders total %s page %s", (total, page, expected) => {
    const wrapper = mount(NumberPagination, { props: { total, page } });
    expect(wrapper.findAll("[data-page-slot]").map(item => item.text()).join(" ")).toBe(expected);
    expect(wrapper.findAll("button[aria-current=page]")).toHaveLength(1);
    expect(wrapper.findAll("button").some(item => item.text() === "…")).toBe(false);
  });
  it("emits real page changes and disables boundary and loading actions", async () => {
    const wrapper = mount(NumberPagination, { props: { total: 200, page: 1 } });
    expect(wrapper.get("button[aria-label=上一页]").attributes("disabled")).toBeDefined();
    await wrapper.get("button[aria-label='第 20 页']").trigger("click");
    expect(wrapper.emitted("change")).toEqual([[20]]);
    await wrapper.setProps({ page: 20 });
    expect(wrapper.get("button[aria-label=下一页]").attributes("disabled")).toBeDefined();
    await wrapper.setProps({ loading: true });
    expect(wrapper.findAll("button").every(button => button.attributes("disabled") !== undefined)).toBe(true);
  });
});
