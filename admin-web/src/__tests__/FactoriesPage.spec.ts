import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";

import { identityApi, type Factory } from "@/api/client";
import FactoriesPage from "@/pages/FactoriesPage.vue";

vi.mock("vue-router", () => ({ useRouter: () => ({ push: vi.fn() }) }));

const factory = {
  factoryId: "factory-a10",
  supplierNumber: "A10",
  factoryName: "禹帆",
  factoryCode: "YF",
  legalName: "温岭市新河禹帆制帽厂",
  address: "浙江省温岭市",
  legalRepresentative: "徐陈杰",
  contacts: [{ name: "王超", phone: "13858645122", displayOrder: 1, isPrimary: true }],
  contractComplete: true,
  missingContractFields: [],
  connectedUsers: 1,
  isEnabled: true,
  version: 1,
} satisfies Factory;

afterEach(() => vi.restoreAllMocks());

describe("factory editor", () => {
  it("matches the approved prototype contact and address rows", async () => {
    vi.spyOn(identityApi, "listFactoryPage").mockResolvedValue({
      items: [factory], total: 1,
    });
    const wrapper = mount(FactoriesPage, {
      global: {
        stubs: {
          AdminShell: { template: "<div><slot /></div>" },
          TableSortButton: { template: "<button><slot /></button>" },
        },
      },
    });
    await flushPromises();

    await wrapper.get(".factory-row-actions button:last-child").trigger("click");

    expect(wrapper.text()).not.toContain("添加联系人");
    expect(wrapper.find(".contact-remove").exists()).toBe(false);
    expect(wrapper.get('label[for="factory-address"]').text()).toBe("单位地址");
    expect(wrapper.get("#factory-address").element.parentElement?.classList).toContain("is-wide");
  });
});

it.each([["", ""], [" xz（帽厂） ", "XZ"], ["xz-分厂", "XZ"], ["X Z", null], ["A1", null], ["ſ", null]])("saves or rejects edited code %s", async (input, expected) => {
  vi.spyOn(identityApi, "listFactoryPage").mockResolvedValue({ items: [factory], total: 1 });
  const update = vi.spyOn(identityApi, "updateFactory").mockResolvedValue(factory);
  const wrapper = mount(FactoriesPage, { global: { stubs: { AdminShell: { template: "<div><slot /></div>" }, TableSortButton: true } } });
  await flushPromises();
  await wrapper.get(".factory-row-actions button:last-child").trigger("click");
  await wrapper.get("#factory-code").setValue(input);
  await wrapper.get("form.factory-editor-panel").trigger("submit");
  await flushPromises();
  if (expected === null) {
    expect(update).not.toHaveBeenCalled();
    expect(wrapper.get("[role=dialog] [role=alert]").text()).toBe("工厂代码仅支持 1–32 位英文字母");
  } else {
    expect(update).toHaveBeenCalledWith(factory.factoryId, expect.objectContaining({ factoryCode: expected }));
  }
});


it("requests one database page and keeps only submitted filters during paging", async () => {
  const list = vi.spyOn(identityApi, "listFactoryPage").mockResolvedValue({ items: [factory], total: 25 });
  const wrapper = mount(FactoriesPage, { global: { stubs: { AdminShell: { template: "<div><slot /></div>" } } } });
  await flushPromises();
  expect(list).toHaveBeenCalledTimes(1);
  await wrapper.get('input[type="search"]').setValue("未提交");
  await wrapper.get('[aria-label="第 2 页"]').trigger("click");
  await flushPromises();
  expect(list).toHaveBeenLastCalledWith(expect.objectContaining({ page: 2, pageSize: 10, keyword: "" }));
  expect(wrapper.get(".factory-sequence").text()).toBe("11");
  await wrapper.get(".order-filter-form").trigger("submit");
  await flushPromises();
  expect(list).toHaveBeenLastCalledWith(expect.objectContaining({ page: 1, keyword: "未提交" }));
  wrapper.unmount();
});

it("ignores stale responses and returns to the last valid page after edits", async () => {
  const list = vi.spyOn(identityApi, "listFactoryPage").mockResolvedValue({ items: [factory], total: 25 });
  const wrapper = mount(FactoriesPage, { global: { stubs: { AdminShell: { template: "<div><slot /></div>" } } } });
  await flushPromises();
  let resolveOld!: (value: { items: Factory[]; total: number }) => void;
  list.mockImplementationOnce(() => new Promise((resolve) => { resolveOld = resolve; }));
  await wrapper.get('[aria-label="第 2 页"]').trigger("click");
  list.mockResolvedValueOnce({ items: [], total: 10 }).mockResolvedValueOnce({ items: [{ ...factory, factoryName: "最新工厂" }], total: 10 });
  await wrapper.get('[aria-label="第 3 页"]').trigger("click");
  await flushPromises();
  expect(list).toHaveBeenLastCalledWith(expect.objectContaining({ page: 1 }));
  resolveOld({ items: [{ ...factory, factoryName: "过期工厂" }], total: 25 });
  await flushPromises();
  expect(wrapper.text()).toContain("最新工厂");
  expect(wrapper.text()).not.toContain("过期工厂");
  expect(wrapper.get(".factory-sequence").text()).toBe("1");
  wrapper.unmount();
});
