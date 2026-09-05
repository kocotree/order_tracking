import { shipmentApi, type CatalogItem, type DraftBoxWrite, type Shipment } from "../../api/shipments";
import { isDevPreview, PREVIEW_SHIPMENT_CATALOG } from "../../modules/dev-preview";
import { newShipmentEvidencePhoto, submitShipmentWithEvidence, uploadShipmentEvidence, type ShipmentEvidencePhoto } from "../../modules/shipment-evidence";

import { ShipmentDraftSession } from "../../modules/shipment-draft";

type BoxView = DraftBoxWrite & { total: number };
type CatalogChoice = CatalogItem & { orderLabel: string };
type PackedItemView = { assignmentId: number; quantity: number; productName: string; propertiesValue: string; orderNo: string };
type PreviewBox = { boxNo: number; total: number; itemCount: number; items: PackedItemView[]; expanded: boolean };
type ProductSummary = { productName: string; quantity: number; specCount: number; items: PackedItemView[]; expanded: boolean };

function confirmModal(title: string, content: string, confirmText = "确定", cancelText = "取消"): Promise<boolean> {
  return new Promise((resolve,reject) => wx.showModal({title,content,confirmText,cancelText,
    success: result => resolve(result.confirm), fail: reject}));
}

Page({
  draftSession: null as ShipmentDraftSession | null,
  saveTimer: null as ReturnType<typeof setTimeout> | null,
  pageClosed: false,
  data: {
    step: 1, boxCount: "", boxes: [] as BoxView[], currentBox: 0,
    catalog: [] as CatalogItem[], productNames: [] as string[], productIndex: 0,
    specOptions: [] as CatalogItem[], specIndex: 0, orderOptions: [] as CatalogChoice[], orderIndex: 0,
    selectedCatalog: null as CatalogItem | null, selectedPackedQuantity: 0, selectedRemainingQuantity: 0,
    packedBoxCount: 0, currentItems: [] as PackedItemView[], previewBoxes: [] as PreviewBox[],
    productSummaries: [] as ProductSummary[], quantity: "", photos: [] as ShipmentEvidencePhoto[], note: "",
    previewMode: false, loading: false, totalQuantity: 0, draftId: "", uploadError: "",
    expandedProducts: [] as string[], expandedBoxes: [] as number[],
    ready: false, saveMessage: "",
  },

  onLoad(options: Record<string, string | undefined>) {
    this.pageClosed = false;
    this.draftSession = new ShipmentDraftSession(shipmentApi);
    const previewMode = isDevPreview(options);
    this.setData({ previewMode, catalog: previewMode ? PREVIEW_SHIPMENT_CATALOG : [] });
    if (previewMode) { this.setData({ready:true}); this.refreshDerived(); }
    else void this.loadCatalog();
  },

  async loadCatalog() {
    this.setData({loading:true, ready:false});
    try {
      const [catalog, draft] = await Promise.all([shipmentApi.catalog(), shipmentApi.currentDraft()]);
      this.setData({catalog:catalog.items});
      if (draft) {
        let resume = await confirmModal("有未提交的发货草稿", "是否继续填写上次保存的内容？", "继续填写", "重新创建");
        if (!resume) {
          const restart = await confirmModal("重新创建发货单", "将放弃当前草稿的装箱内容、凭证和备注，是否继续？", "重新创建");
          if (restart) await shipmentApi.abandonDraft(draft.shipmentId,draft.version);
          else resume = true;
        }
        if (resume) await this.restoreDraft(draft);
      }
      this.setData({ready:true});
      this.refreshDerived();
    } catch {
      this.setData({saveMessage:"草稿或产品加载失败，请退出后重试"});
      wx.showToast({title:"草稿加载失败，请重新进入",icon:"none"});
    } finally { this.setData({loading:false}); }
  },

  async restoreDraft(draft: Shipment) {
    this.draftSession!.resume(draft);
    const boxes = draft.boxes.map(box => ({boxNo:box.boxNo,groupKey:box.groupKey,
      items:box.items.map(item => ({assignmentId:item.assignmentId,quantity:item.quantity})),
      total:box.items.reduce((sum,item) => sum+item.quantity,0)}));
    const photos = await Promise.all(draft.files.map(async file => {
      const photo: ShipmentEvidencePhoto = {localPath:"",uploadKey:`stored-${file.fileId}`,
        fileId:file.fileId,status:"uploaded",progress:100};
      try { photo.localPath = await shipmentApi.downloadFile(file); }
      catch { photo.downloadFailed = true; }
      return photo;
    }));
    this.setData({draftId:draft.shipmentId,boxes,boxCount:String(boxes.length || ""),note:draft.note,
      photos,step:boxes.length ? 2 : 1,currentBox:0,saveMessage:"草稿已保存"});
  },

  async saveDraftNow(): Promise<boolean> {
    if (this.saveTimer) { clearTimeout(this.saveTimer); this.saveTimer=null; }
    if (this.data.previewMode) return true;
    if (!this.data.ready || !this.data.boxes.length) return false;
    if (!this.pageClosed) this.setData({saveMessage:"正在保存草稿…"});
    try {
      const draft = await this.draftSession!.save(this.data.boxes.map(({boxNo,groupKey,items}) => ({boxNo,groupKey,items})),this.data.note);
      const writes = (boxes: DraftBoxWrite[]) => boxes.map(box => ({boxNo:box.boxNo,groupKey:box.groupKey,
        items:box.items.map(item => ({assignmentId:item.assignmentId,quantity:item.quantity}))}));
      const isLatest = JSON.stringify(writes(draft.boxes)) === JSON.stringify(writes(this.data.boxes)) && draft.note === this.data.note.trim();
      if (!this.pageClosed) this.setData({draftId:draft.shipmentId,saveMessage:isLatest ? "草稿已保存" : "有修改尚未保存"});
      return true;
    } catch (error) {
      const message = (error as {statusCode?:number}).statusCode === 409
        ? "草稿已在其他页面更新，本页修改未保存，请重新进入核对"
        : "草稿未保存，请检查网络后重试下一步";
      if (!this.pageClosed) this.setData({saveMessage:message});
      return false;
    }
  },

  scheduleSave() {
    if (this.data.previewMode || !this.data.draftId) return;
    this.setData({saveMessage:"有修改尚未保存"});
    if (this.saveTimer) clearTimeout(this.saveTimer);
    this.saveTimer=setTimeout(() => { this.saveTimer=null; void this.saveDraftNow(); },500);
  },

  onHide() {
    if (this.data.draftId && this.data.ready && !this.data.loading) void this.saveDraftNow();
  },
  onUnload() {
    if (this.saveTimer) clearTimeout(this.saveTimer);
    this.saveTimer=null;
    this.pageClosed=true;
    if (this.data.draftId && this.data.ready && !this.data.loading) void this.saveDraftNow();
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
  async generateBoxes() {
    if (this.data.loading || !this.data.ready) return;
    const count = Number(this.data.boxCount);
    if (!Number.isInteger(count) || count < 1) { wx.showToast({ title: "请填写正确的总箱数", icon: "none" }); return; }
    if (this.data.boxes.slice(count).some(box => box.items.length)) {
      this.setData({loading:true});
      try { if (!await confirmModal("减少箱数", "将移除超出总箱数的箱及其装箱内容，是否继续？")) return; }
      finally { this.setData({loading:false}); }
    }
    this.setData({ boxes: Array.from({ length: count }, (_, index) => this.data.boxes[index] || ({ boxNo: index + 1, groupKey: null, items: [], total: 0 })), currentBox: 0 });
    this.refreshDerived();
    this.scheduleSave();
  },
  selectBox(event: WechatMiniprogram.TouchEvent) { this.setData({ currentBox: Number(event.currentTarget.dataset.index), quantity: "" }); this.refreshDerived(); },
  productChanged(event: WechatMiniprogram.PickerChange) { this.setData({ productIndex: Number(event.detail.value), specIndex: 0, orderIndex: 0, quantity: "" }); this.refreshDerived(); },
  specChanged(event: WechatMiniprogram.PickerChange) { this.setData({ specIndex: Number(event.detail.value), orderIndex: 0, quantity: "" }); this.refreshDerived(); },
  orderChanged(event: WechatMiniprogram.PickerChange) { this.setData({ orderIndex: Number(event.detail.value), quantity: "" }); this.refreshDerived(); },
  quantityChanged(event: WechatMiniprogram.Input) { this.setData({ quantity: event.detail.value }); },

  addItem() {
    if (this.data.loading || !this.data.ready) return;
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
    this.scheduleSave();
  },

  removeItem(event: WechatMiniprogram.TouchEvent) {
    if (this.data.loading || !this.data.ready) return;
    const assignmentId = Number(event.currentTarget.dataset.assignmentId);
    const boxes = this.data.boxes.map((box, index) => {
      if (index !== this.data.currentBox) return box;
      const items = box.items.filter((item) => item.assignmentId !== assignmentId);
      return { ...box, items, total: items.reduce((sum, item) => sum + item.quantity, 0) };
    });
    this.setData({ boxes });
    this.refreshDerived();
    this.scheduleSave();
  },

  choosePhoto() {
    if (this.data.loading || !this.data.ready || this.data.photos.length >= 3) return;
    wx.chooseMedia({
      count: 3 - this.data.photos.length,
      mediaType: ["image"],
      success: async (result) => {
        if (this.pageClosed) return;
        this.setData({loading:true});
        try {
          const added: ShipmentEvidencePhoto[] = [];
          for (const file of result.tempFiles) {
            const localPath = await new Promise<string>((resolve, reject) => wx.compressImage({ src: file.tempFilePath, quality: 80, success: value => resolve(value.tempFilePath), fail: reject }));
            added.push(newShipmentEvidencePhoto(localPath));
          }
          this.setData({ photos: [...this.data.photos, ...added].slice(0, 3), uploadError: "" });
          await this.savePhotos();
        } catch { wx.showToast({ title: "凭证处理失败，请重试", icon: "none" }); }
        finally { this.setData({loading:false}); }
      },
    });
  },
  async savePhotos(): Promise<boolean> {
    if (this.data.previewMode) return true;
    if (!await this.saveDraftNow()) return false;
    try {
      await uploadShipmentEvidence({shipmentId:this.data.draftId,photos:this.data.photos,
        uploadFile:(id,photo,onProgress) => shipmentApi.uploadFile(id,photo.localPath,photo.uploadKey,onProgress),
        onPhotosChange:photos => { if (!this.pageClosed) this.setData({photos}); }});
      this.setData({uploadError:""});
      return true;
    } catch {
      this.setData({uploadError:"凭证尚未保存，下一步可重试；退出可能丢失未上传图片"});
      return false;
    }
  },
  async removePhoto(event: WechatMiniprogram.TouchEvent) {
    if (this.data.loading || !this.data.ready) return;
    const index = Number(event.currentTarget.dataset.index);
    const photo = this.data.photos[index];
    if (!photo) return;
    this.setData({loading:true});
    try {
      if (photo.fileId && this.data.draftId) await shipmentApi.removeFile(this.data.draftId, photo.fileId);
      this.setData({ photos: this.data.photos.filter((_, itemIndex) => itemIndex !== index), uploadError: "" });
    } catch { wx.showToast({ title: "凭证移除失败，请重试", icon: "none" }); }
    finally { this.setData({loading:false}); }
  },
  noteChanged(event: WechatMiniprogram.TextareaInput) { if(this.data.loading)return; this.setData({ note: event.detail.value }); this.scheduleSave(); },
  async next() {
    if (this.data.loading || !this.data.ready) return;
    if (this.data.step === 1 && !this.data.boxes.length) { wx.showToast({ title: "请先生成箱号", icon: "none" }); return; }
    if (this.data.step === 2 && this.data.boxes.some((box) => !box.items.length)) { wx.showToast({ title: "请填写每个箱子的装箱内容", icon: "none" }); return; }
    this.setData({loading:true});
    try {
      if (!await this.savePhotos()) return;
      this.setData({ step: Math.min(4, this.data.step + 1) }); this.refreshDerived();
    } finally { this.setData({loading:false}); }
  },
  async previous() {
    if(this.data.loading || !this.data.ready)return;
    this.setData({loading:true});
    try { if(await this.savePhotos()) this.setData({step:Math.max(1,this.data.step-1)}); }
    finally { this.setData({loading:false}); }
  },
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
    if(this.data.loading || !this.data.ready)return;
    if (this.data.previewMode) { wx.showToast({ title: "预览提交成功", icon: "success" }); setTimeout(() => wx.redirectTo({ url: "/pages/factory-shipment-detail/factory-shipment-detail?shipmentId=preview-shipment&preview=1" }), 500); return; }
    this.setData({ loading: true });
    try {
      if(!await this.savePhotos()) return;
      const result = await submitShipmentWithEvidence({
        photos: this.data.photos,
        boxes: this.data.boxes.map(({ boxNo, groupKey, items }) => ({ boxNo, groupKey, items })),
        note: this.data.note,
        gateway: {
          createDraft: async () => this.draftSession!.current!,
          saveDraft: async () => { if(!await this.saveDraftNow()) throw new Error("草稿未保存"); },
          uploadFile: (shipmentId, photo, onProgress) => shipmentApi.uploadFile(shipmentId, photo.localPath, photo.uploadKey, onProgress),
          submitDraft: id => shipmentApi.submitDraft(id,this.draftSession!.current!.version),
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
  async goBack() {
    if(this.data.loading)return;
    if(this.data.step>1) { await this.previous(); return; }
    if(this.data.draftId && !await this.saveDraftNow()) return;
    wx.navigateBack();
  },
});
