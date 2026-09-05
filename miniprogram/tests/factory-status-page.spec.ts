import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ getMyApplication: vi.fn() }));

vi.mock("../api/factory", () => ({
  factoryApi: {
    getMyApplication: mocks.getMyApplication,
  },
}));

type FactoryStatusPage = {
  data: {
    status: string;
    application: Record<string, unknown> | null;
    submittedAtText: string;
    factoryName: string;
    loading: boolean;
    previewMode: boolean;
  };
  setData(values: Partial<FactoryStatusPage["data"]>): void;
  refresh(): Promise<void>;
};

let page: FactoryStatusPage;

beforeEach(async () => {
  vi.resetModules();
  mocks.getMyApplication.mockReset();
  vi.stubGlobal("Page", (definition: FactoryStatusPage) => {
    page = {
      ...definition,
      data: { ...definition.data },
      setData(values) {
        Object.assign(this.data, values);
      },
    };
  });
  vi.stubGlobal("wx", {
    redirectTo: vi.fn(),
    reLaunch: vi.fn(),
  });
  await import("../pages/factory-status/factory-status");
});

describe("factory application status presentation", () => {
  it("formats the submitted time returned by the API", async () => {
    mocks.getMyApplication.mockResolvedValue({
      status: "pending",
      submittedAt: "2026-09-05T08:30:00.123456",
    });

    await page.refresh();

    expect(page.data.submittedAtText).toBe("2026-09-05 16:30");
    expect(page.data.status).toBe("pending");
  });
});
