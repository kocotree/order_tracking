import { shipmentApi, type CatalogItem, type DraftBoxWrite } from "../../api/shipments";
import { isDevPreview, PREVIEW_SHIPMENT_CATALOG } from "../../modules/dev-preview";
import { newShipmentEvidencePhoto, submitShipmentWithEvidence, type ShipmentEvidencePhoto } from "../../modules/shipment-evidence";

type BoxView = DraftBoxWrite & { total: number };
type CatalogChoice = CatalogItem & { orderLabel: string };
type PackedItemView = { assignmentId: number; quantity: number; productName: string; propertiesValue: string; orderNo: string };
type PreviewBox = { boxNo: number; total: number; itemCount: number; items: PackedItemView[]; expanded: boolean };
type ProductSummary = { productName: string; quantity: number; specCount: number; items: PackedItemView[]; expanded: boolean };

Page({
  data: {
    step: 1, boxCount: "", boxes: [] as BoxView[], currentBox: 0,
    catalog: [] as CatalogItem[], productNames: [] as string[], productIndex: 0,
    specOptions: [] as CatalogItem[], specIndex: 0, orderOptions: [] as CatalogChoice[], orderIndex: 0,
    selectedCatalog: null as CatalogItem | null, selectedPackedQuantity: 0, selectedRemainingQuantity: 0,
    packedBoxCount: 0, currentItems: [] as PackedItemView[], previewBoxes: [] as PreviewBox[],
    productSummaries: [] as ProductSummary[], quantity: "", photos: [] as ShipmentEvidencePhoto[], note: "",
    previewMode: false, loading: false, totalQuantity: 0, draftId: "", uploadError: "",
    expandedProducts: [] as string[], expandedBoxes: [] as number[],
  },

  onLoad(options: Record<string, string | undefined>) {
    const previewMode = isDevPreview(options);
    this.setData({ previewMode, catalog: previewMode ? PREVIEW_SHIPMENT_CATALOG : [] });
    if (previewMode) this.refreshDerived();
    else void this.loadCatalog();
  },

  async loadCatalog() {
    try {
      this.setData({ catalog: (await shipmentApi.catalog()).items });
      this.refreshDerived();
    } catch {
      wx.showToast({ title: "可发产品加载失败", icon: "none" });
    }
  },

  refreshDerived() {
    const catalog = this.data.catalog;
    const productNames = Array.from(new Set(catalog.map((item) => item.productName)));
    const productIndex = Math.min(this.data.productIndex, Math.max(productNames.length - 1, 0));
    const productName = productNames[productIndex] || "";
    const productCatalog = catalog.filter((item) => item.productName === productName);
    const specNames = Array.from(new Set(productCatalog.map((item) => item.propertiesValue)));
    const specIndex = Math.min(this.data.specIndex, Math.max(specNames.length - 1, 0));
    const specName = specNames[specIndex] || "";
    const specOptions = specNames.map((name) => productCatalog.find((item) => item.propertiesValue === name)!).filter(Boolean);
    const orderOptions = productCatalog
      .filter((item) => item.propertiesValue === specName)
      .map((item) => ({ ...item, orderLabel: `${item.orderNo} · 合同出货时间 ${item.contractShipDate}` }));
    const orderIndex = Math.min(this.data.orderIndex, Math.max(orderOptions.length - 1, 0));
    const selectedCatalog = orderOptions[orderIndex] || null;
    const selectedPackedQuantity = selectedCatalog
      ? this.data.boxes.reduce((sum, box) => sum + (box.items.find((item) => item.assignmentId === selectedCatalog.assignmentId)?.quantity || 0), 0)
      : 0;

    const toPackedView = (item: { assignmentId: number; quantity: number }): PackedItemView => {
      const detail = catalog.find((candidate) => candidate.assignmentId === item.assignmentId);
      return { assignmentId: item.assignmentId, quantity: item.quantity, productName: detail?.productName || "—", propertiesValue: detail?.propertiesValue || "—", orderNo: detail?.orderNo || "—" };
    };
    const previewBoxes = this.data.boxes.map((box) => ({ boxNo: box.boxNo, total: box.total, itemCount: box.items.length, items: box.items.map(toPackedView), expanded: this.data.expandedBoxes.includes(box.boxNo) }));
    const productMap = new Map<string, { quantity: number; specs: Set<string>; items: PackedItemView[] }>();
    previewBoxes.forEach((box) => box.items.forEach((item) => {
      const current = productMap.get(item.productName) || { quantity: 0, specs: new Set<string>(), items: [] };
      current.quantity += item.quantity;
      current.specs.add(`${item.orderNo}\u0001${item.propertiesValue}`);
      const existing = current.items.find((candidate) => candidate.assignmentId === item.assignmentId);
      if (existing) existing.quantity += item.quantity;
      else current.items.push({ ...item });
      productMap.set(item.productName, current);
    }));
    const productSummaries = Array.from(productMap, ([name, summary]) => ({ productName: name, quantity: summary.quantity, specCount: summary.specs.size, items: summary.items, expanded: this.data.expandedProducts.includes(name) }));
    const currentItems = previewBoxes[this.data.currentBox]?.items || [];
    const totalQuantity = this.data.boxes.reduce((sum, box) => sum + box.total, 0);

    this.setData({
      productNames, productIndex, specOptions, specIndex, orderOptions, orderIndex, selectedCatalog,
      selectedPackedQuantity, selectedRemainingQuantity: selectedCatalog ? selectedCatalog.pendingQuantity - selectedPackedQuantity : 0,
      packedBoxCount: this.data.boxes.filter((box) => box.items.length > 0).length,
      currentItems, previewBoxes, productSummaries, totalQuantity,
    });
  },

  boxCountChanged(event: WechatMiniprogram.Input) { this.setData({ boxCount: event.detail.value }); },
  generateBoxes() {
    const count = Number(this.data.boxCount);
    if (!Number.isInteger(count) || count < 1) { wx.showToast({ title: "请填写正确的总箱数", icon: "none" }); return; }
    this.setData({ boxes: Array.from({ length: count }, (_, index) => ({ boxNo: index + 1, groupKey: null, items: [], total: 0 })), currentBox: 0 });
    this.refreshDerived();
  },
  selectBox(event: WechatMiniprogram.TouchEvent) { this.setData({ currentBox: Number(event.currentTarget.dataset.index), quantity: "" }); this.refreshDerived(); },
  productChanged(event: WechatMiniprogram.PickerChange) { this.setData({ productIndex: Number(event.detail.value), specIndex: 0, orderIndex: 0, quantity: "" }); this.refreshDerived(); },
  specChanged(event: WechatMiniprogram.PickerChange) { this.setData({ specIndex: Number(event.detail.value), orderIndex: 0, quantity: "" }); this.refreshDerived(); },
  orderChanged(event: WechatMiniprogram.PickerChange) { this.setData({ orderIndex: Number(event.detail.value), quantity: "" }); this.refreshDerived(); },
  quantityChanged(event: WechatMiniprogram.Input) { this.setData({ quantity: event.detail.value }); },

  addItem() {
    const quantity = Number(this.data.quantity);
    const catalogItem = this.data.selectedCatalog;
    if (!catalogItem || !Number.isInteger(quantity) || quantity < 1) { wx.showToast({ title: "请选择产品并填写数量", icon: "none" }); return; }
    const boxes = this.data.boxes.map((box, index) => {
      if (index !== this.data.currentBox) return box;
      const existing = box.items.find((item) => item.assignmentId === catalogItem.assignmentId);
      const items = existing
        ? box.items.map((item) => item.assignmentId === catalogItem.assignmentId ? { ...item, quantity: item.quantity + quantity } : item)
        : [...box.items, { assignmentId: catalogItem.assignmentId, quantity }];
      return { ...box, items, total: items.reduce((sum, item) => sum + item.quantity, 0) };
    });
    this.setData({ boxes, quantity: "" });
    this.refreshDerived();
  },

  removeItem(event: WechatMiniprogram.TouchEvent) {
    const assignmentId = Number(event.currentTarget.dataset.assignmentId);
    const boxes = this.data.boxes.map((box, index) => {
      if (index !== this.data.currentBox) return box;
      const items = box.items.filter((item) => item.assignmentId !== assignmentId);
      return { ...box, items, total: items.reduce((sum, item) => sum + item.quantity, 0) };
    });
    this.setData({ boxes });
    this.refreshDerived();
  },

  choosePhoto() {
    wx.chooseMedia({
      count: 3 - this.data.photos.length,
      mediaType: ["image"],
      success: async (result) => {
        try {
          const added: ShipmentEvidencePhoto[] = [];
          for (const file of result.tempFiles) {
            const localPath = await new Promise<string>((resolve, reject) => wx.compressImage({ src: file.tempFilePath, quality: 80, success: value => resolve(value.tempFilePath), fail: reject }));
            added.push(newShipmentEvidencePhoto(localPath));
          }
          this.setData({ photos: [...this.data.photos, ...added].slice(0, 3), uploadError: "" });
        } catch { wx.showToast({ title: "图片压缩失败，请重试", icon: "none" }); }
      },
    });
  },
  async removePhoto(event: WechatMiniprogram.TouchEvent) {
    const index = Number(event.currentTarget.dataset.index);
    const photo = this.data.photos[index];
    if (!photo) return;
    try {
      if (photo.fileId && this.data.draftId) await shipmentApi.removeFile(this.data.draftId, photo.fileId);
      this.setData({ photos: this.data.photos.filter((_, itemIndex) => itemIndex !== index), uploadError: "" });
    } catch { wx.showToast({ title: "凭证移除失败，请重试", icon: "none" }); }
  },
  noteChanged(event: WechatMiniprogram.TextareaInput) { this.setData({ note: event.detail.value }); },
  next() {
    if (this.data.step === 1 && !this.data.boxes.length) { wx.showToast({ title: "请先生成箱号", icon: "none" }); return; }
    if (this.data.step === 2 && this.data.boxes.some((box) => !box.items.length)) { wx.showToast({ title: "请填写每个箱子的装箱内容", icon: "none" }); return; }
    this.setData({ step: Math.min(4, this.data.step + 1) }); this.refreshDerived();
  },
  previous() { this.setData({ step: Math.max(1, this.data.step - 1) }); },
  toggleProduct(event: WechatMiniprogram.TouchEvent) {
    const productName = String(event.currentTarget.dataset.productName);
    const expandedProducts = this.data.expandedProducts.includes(productName)
      ? this.data.expandedProducts.filter((name) => name !== productName)
      : [...this.data.expandedProducts, productName];
    this.setData({ expandedProducts });
    this.refreshDerived();
  },
  toggleBox(event: WechatMiniprogram.TouchEvent) {
    const boxNo = Number(event.currentTarget.dataset.boxNo);
    const expandedBoxes = this.data.expandedBoxes.includes(boxNo)
      ? this.data.expandedBoxes.filter((value) => value !== boxNo)
      : [...this.data.expandedBoxes, boxNo];
    this.setData({ expandedBoxes });
    this.refreshDerived();
  },
  async submit() {
    if (this.data.previewMode) { wx.showToast({ title: "预览提交成功", icon: "success" }); setTimeout(() => wx.redirectTo({ url: "/pages/factory-shipment-detail/factory-shipment-detail?shipmentId=preview-shipment&preview=1" }), 500); return; }
    this.setData({ loading: true });
    try {
      const result = await submitShipmentWithEvidence({
        photos: this.data.photos,
        boxes: this.data.boxes.map(({ boxNo, groupKey, items }) => ({ boxNo, groupKey, items })),
        note: this.data.note,
        gateway: {
          createDraft: async () => { const draft = await shipmentApi.createDraft(); this.setData({ draftId: draft.shipmentId }); return draft; },
          saveDraft: shipmentApi.saveDraft,
          uploadFile: (shipmentId, photo, onProgress) => shipmentApi.uploadFile(shipmentId, photo.localPath, photo.uploadKey, onProgress),
          submitDraft: shipmentApi.submitDraft,
        },
        onPhotosChange: photos => this.setData({ photos }),
      });
      const submitted = result.shipment;
      wx.redirectTo({ url: `/pages/factory-shipment-detail/factory-shipment-detail?shipmentId=${encodeURIComponent(submitted.shipmentId)}` });
    } catch {
      const uploadFailed = this.data.photos.some(photo => photo.status === "failed");
      this.setData({ uploadError: uploadFailed ? "凭证上传失败，发货单尚未提交，可点击重试" : "" });
      wx.showToast({ title: uploadFailed ? "凭证上传失败，请重试" : "提交失败，请检查装箱数量", icon: "none" });
    }
    finally { this.setData({ loading: false }); }
  },
  goBack() { if (this.data.step > 1) this.previous(); else wx.navigateBack(); },
});
