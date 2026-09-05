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
    vi.spyOn(identityApi, "listFactories").mockResolvedValue({
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
  vi.spyOn(identityApi, "listFactories").mockResolvedValue({ items: [factory], total: 1 });
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
