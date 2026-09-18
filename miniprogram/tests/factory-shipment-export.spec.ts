import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { PREVIEW_SHIPMENT } from "../modules/dev-preview";
import type { Shipment } from "../api/shipments";

interface DetailPage {
  data: {
    shipment: Shipment | null;
    downloadingManifest: boolean;
    canDownloadManifest: boolean;
  };
  setData(data: Partial<DetailPage["data"]>): void;
  showShipment(shipment: Shipment): void;
  downloadManifest(): Promise<void>;
}

let page: DetailPage;
const unlink = vi.fn((options: WechatMiniprogram.UnlinkOption) => options.complete?.({ errMsg: "unlink:ok", errCode: 0 }));

beforeEach(async () => {
  vi.resetModules();
  unlink.mockClear();
  vi.stubGlobal("Page", (definition: DetailPage) => {
    page = definition;
    page.setData = data => Object.assign(page.data, data);
  });
  vi.stubGlobal("wx", {
    getStorageSync: () => "factory-token",
    getAccountInfoSync: () => ({ miniProgram: { envVersion: "develop" } }),
    downloadFile: vi.fn((options: WechatMiniprogram.DownloadFileOption) =>
      options.success?.({ statusCode: 200, tempFilePath: "/tmp/shipment.xlsx" } as WechatMiniprogram.DownloadFileSuccessCallbackResult)),
    openDocument: vi.fn((options: WechatMiniprogram.OpenDocumentOption) => options.success?.({ errMsg: "openDocument:ok" })),
    getFileSystemManager: () => ({ unlink }),
    showToast: vi.fn(),
  });
  await import("../pages/factory-shipment-detail/factory-shipment-detail");
  page.showShipment({ ...PREVIEW_SHIPMENT, files: [] });
});

afterEach(() => vi.unstubAllGlobals());

it("downloads, opens, and removes the temporary shipment workbook", async () => {
  expect(page.data.canDownloadManifest).toBe(true);
  await page.downloadManifest();

  expect(wx.showToast).not.toHaveBeenCalled();
  expect(wx.downloadFile).toHaveBeenCalledWith(expect.objectContaining({
    url: expect.stringContaining("/factory/shipments/preview-shipment/export"),
    header: { Authorization: "Bearer factory-token" },
  }));
  expect(wx.openDocument).toHaveBeenCalledWith(expect.objectContaining({
    filePath: "/tmp/shipment.xlsx",
    fileType: "xlsx",
    showMenu: true,
  }));
  expect(unlink).toHaveBeenCalledWith(expect.objectContaining({ filePath: "/tmp/shipment.xlsx" }));
  expect(page.data.downloadingManifest).toBe(false);
});

it("does not download withdrawn shipments", async () => {
  page.showShipment({ ...PREVIEW_SHIPMENT, files: [], status: "WITHDRAWN" });
  await page.downloadManifest();

  expect(page.data.canDownloadManifest).toBe(false);
  expect(wx.downloadFile).not.toHaveBeenCalled();
});

it("ignores repeated taps while the workbook is downloading", async () => {
  let finishDownload!: () => void;
  vi.mocked(wx.downloadFile).mockImplementation(options => {
    finishDownload = () => options.success?.({
      statusCode: 200,
      tempFilePath: "/tmp/shipment.xlsx",
    } as WechatMiniprogram.DownloadFileSuccessCallbackResult);
    return {} as WechatMiniprogram.DownloadTask;
  });

  const first = page.downloadManifest();
  const repeated = page.downloadManifest();
  expect(page.data.downloadingManifest).toBe(true);
  expect(wx.downloadFile).toHaveBeenCalledTimes(1);
  finishDownload();
  await Promise.all([first, repeated]);
  expect(page.data.downloadingManifest).toBe(false);
});

it("reports download failures and restores the button", async () => {
  vi.mocked(wx.downloadFile).mockImplementation(options => {
    options.success?.({ statusCode: 500, tempFilePath: "" } as WechatMiniprogram.DownloadFileSuccessCallbackResult);
    return {} as WechatMiniprogram.DownloadTask;
  });

  await page.downloadManifest();

  expect(wx.showToast).toHaveBeenCalledWith({ title: "清单下载失败，请稍后重试", icon: "none" });
  expect(wx.openDocument).not.toHaveBeenCalled();
  expect(unlink).not.toHaveBeenCalled();
  expect(page.data.downloadingManifest).toBe(false);
});

it("reports open failures, removes the temporary file, and restores the button", async () => {
  vi.mocked(wx.openDocument).mockImplementation(options => {
    options.fail?.({ errMsg: "openDocument:fail" });
  });

  await page.downloadManifest();

  expect(wx.showToast).toHaveBeenCalledWith({ title: "清单打开失败，请稍后重试", icon: "none" });
  expect(unlink).toHaveBeenCalledWith(expect.objectContaining({ filePath: "/tmp/shipment.xlsx" }));
  expect(page.data.downloadingManifest).toBe(false);
});
