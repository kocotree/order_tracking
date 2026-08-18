import { repairImportPreview, repairListData } from "../mock-data.js";
import { escapeHTML, showToast } from "../components/app-shell.js";
import { getNextSortState, renderSortableHeader, sortRows, updateSortHeaders } from "../components/table-sort.js";

const backIcon = `<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="m15 18-6-6 6-6" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>`;
const uploadIcon = `<svg viewBox="0 0 48 48" fill="none" aria-hidden="true"><path d="M24 33V12m0 0-8 8m8-8 8 8M10 34v4h28v-4" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/></svg>`;
const photoIcon = `<svg viewBox="0 0 32 32" fill="none" aria-hidden="true"><rect x="4" y="6" width="24" height="20" rx="2" stroke="currentColor" stroke-width="1.6"/><circle cx="12" cy="13" r="2.5" stroke="currentColor" stroke-width="1.6"/><path d="m7 23 7-7 4 4 3-3 4 6" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>`;

function formatNumber(value) {
  return new Intl.NumberFormat("zh-CN").format(Number(value) || 0);
}

function renderPreviewRows(lines) {
  return lines.map((line, index) => `
    <tr>
      <td class="order-sequence-cell">${index + 1}</td>
      <td class="detail-code">${escapeHTML(line.code)}</td>
      <td>${escapeHTML(line.name)}</td>
      <td>${escapeHTML(line.colorSpec)}</td>
      <td class="repair-number-cell">${escapeHTML(formatNumber(line.quantity))}</td>
      <td>${escapeHTML(line.boxNo)}</td>
      <td class="repair-reason-cell" title="${escapeHTML(line.reason || "—")}">${escapeHTML(line.reason || "—")}</td>
      <td>
        ${line.photoCount
          ? `<button class="repair-photo-button" type="button" data-preview-photo="${index}">${photoIcon}<span>${line.photoCount} 张</span></button>`
          : `<button class="repair-photo-button is-empty" type="button" data-preview-photo-upload="${index}">${photoIcon}<span>补传</span></button>`}
      </td>
    </tr>
  `).join("");
}

export function renderRepairCreatePage() {
  return `
    <article class="order-detail-page repair-create-page" data-repair-create-page>
      <section class="section-card detail-overview-card">
        <header class="detail-page-header">
          <button class="detail-back-button" type="button" data-repair-create-back>${backIcon}<span>返回</span></button>
          <div class="detail-title-row repair-create-title"><strong>新建返修单</strong></div>
        </header>
        <div class="repair-upload-content">
          <input class="sr-only" type="file" accept=".xlsx,.xls" data-repair-file />
          <button class="repair-upload-zone" type="button" data-repair-upload>
            ${uploadIcon}
            <strong>上传质检 Excel</strong>
            <span>支持 .xlsx、.xls 文件，上传后自动读取工厂、箱号、产品规格、数量、原因和照片。</span>
          </button>
          <div class="repair-uploaded-file" hidden data-repair-uploaded-file>
            <div><span class="repair-file-mark">XLS</span><span><strong data-repair-file-name></strong><small>质检单已读取，可以重新上传替换</small></span></div>
            <div class="repair-file-actions">
              <button class="detail-text-button" type="button" data-repair-original-file>查看原文件</button>
              <button class="detail-outline-button" type="button" data-repair-reupload>重新上传</button>
            </div>
          </div>
        </div>
      </section>

      <section class="section-card detail-section-card repair-preview-card" hidden data-repair-preview>
        <header class="detail-section-header">
          <div><h2>导入预览</h2><p>请核对工厂和明细，确认后系统自动生成返修单号。</p></div>
          <span class="repair-validation-badge">已读取 ${repairImportPreview.lineCount} 条明细</span>
        </header>
        <div class="repair-preview-summary">
          <label><span>工厂</span><select data-repair-factory><option value="旭之梦">旭之梦</option><option value="龙腾">龙腾</option><option value="红燕">红燕</option><option value="众乐鑫">众乐鑫</option></select></label>
          <div><span>仓库退回总数量</span><strong>${escapeHTML(formatNumber(repairImportPreview.warehouseReturnQuantity))}</strong></div>
          <div><span>箱数</span><strong>${escapeHTML(formatNumber(repairImportPreview.boxCount))}</strong></div>
          <div><span>明细条数</span><strong>${escapeHTML(formatNumber(repairImportPreview.lineCount))}</strong></div>
        </div>
        <div class="detail-table-scroll">
          <table class="detail-data-table repair-preview-table data-grid-table" data-sort-table="repair-preview">
            <thead><tr><th scope="col">序号</th>${renderSortableHeader("产品编码", "code")}${renderSortableHeader("产品名称", "name")}${renderSortableHeader("颜色/规格", "colorSpec")}${renderSortableHeader("退回数量", "quantity")}${renderSortableHeader("箱号", "boxNo")}${renderSortableHeader("次品原因", "reason")}<th scope="col">次品照片</th></tr></thead>
            <tbody data-repair-preview-body>${renderPreviewRows(repairImportPreview.lines)}</tbody>
          </table>
        </div>
        <footer class="repair-create-actions">
          <button class="detail-outline-button" type="button" data-repair-create-cancel>取消</button>
          <button class="detail-primary-button" type="button" data-repair-create-submit>确认创建</button>
        </footer>
      </section>
    </article>
  `;
}

function makeRepairNumber() {
  const today = new Date().toISOString().slice(0, 10).replaceAll("-", "");
  const sameDayCount = repairListData.repairs.filter((repair) => repair.repairNo.startsWith(`FX${today}`)).length;
  return `FX${today}-${String(sameDayCount + 1).padStart(3, "0")}`;
}

function currentReturnTime() {
  return new Date().toLocaleString("sv-SE", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).replace("T", " ");
}

export function bindRepairCreatePage() {
  const page = document.querySelector("[data-repair-create-page]");
  const fileInput = page?.querySelector("[data-repair-file]");
  const uploadZone = page?.querySelector("[data-repair-upload]");
  const uploadedFile = page?.querySelector("[data-repair-uploaded-file]");
  const fileName = page?.querySelector("[data-repair-file-name]");
  const preview = page?.querySelector("[data-repair-preview]");
  const previewBody = page?.querySelector("[data-repair-preview-body]");
  let currentFileName = "";
  let previewLines = [...repairImportPreview.lines];
  let sortState = { key: null, direction: "asc" };

  const openFilePicker = () => fileInput?.click();
  const showPreview = (name) => {
    currentFileName = name;
    if (fileName) fileName.textContent = name;
    if (uploadZone) uploadZone.hidden = true;
    if (uploadedFile) uploadedFile.hidden = false;
    if (preview) preview.hidden = false;
  };

  page?.querySelector("[data-repair-create-back]")?.addEventListener("click", () => { window.location.hash = "/repairs"; });
  page?.querySelector("[data-repair-create-cancel]")?.addEventListener("click", () => { window.location.hash = "/repairs"; });
  uploadZone?.addEventListener("click", openFilePicker);
  page?.querySelector("[data-repair-reupload]")?.addEventListener("click", openFilePicker);
  fileInput?.addEventListener("change", () => {
    const selectedFile = fileInput.files?.[0];
    if (!selectedFile) return;
    showPreview(selectedFile.name);
    showToast("质检单读取完成", `已读取 ${repairImportPreview.lineCount} 条明细，请核对后创建。`);
  });
  page?.querySelector("[data-repair-original-file]")?.addEventListener("click", () => showToast("查看原文件", `${currentFileName} 将在正式开发时提供在线查看或下载。`));

  page?.addEventListener("click", (event) => {
    const nextSortState = getNextSortState(event, sortState);
    if (nextSortState) {
      sortState = nextSortState;
      previewLines = sortRows(repairImportPreview.lines, sortState, (line, key) => line[key]);
      updateSortHeaders(page, sortState);
      if (previewBody) previewBody.innerHTML = renderPreviewRows(previewLines);
      return;
    }
    if (event.target.closest("[data-preview-photo]")) showToast("查看次品照片", "原型阶段使用图片占位，正式开发时打开质检单内的原始照片。");
    if (event.target.closest("[data-preview-photo-upload]")) showToast("补传次品照片", "正式开发时可为该条明细补传照片，照片允许为空。若已识别失败也可在这里补传。");
  });

  page?.querySelector("[data-repair-create-submit]")?.addEventListener("click", () => {
    if (!currentFileName) {
      showToast("请先上传质检单", "上传并核对质检 Excel 后才能创建返修任务。");
      return;
    }
    const repairNo = makeRepairNumber();
    const factory = page.querySelector("[data-repair-factory]")?.value || repairImportPreview.factory;
    repairListData.repairs.unshift({
      repairNo,
      factory,
      returnedAt: currentReturnTime(),
      sourceFile: currentFileName,
      warehouseReturnQuantity: repairImportPreview.warehouseReturnQuantity,
      repairedQuantity: 0,
      scrappedQuantity: 0,
      statusKey: "pending",
      statusLabel: "待工厂处理",
      tone: "warning",
      summary: { boxCount: repairImportPreview.boxCount, lineCount: repairImportPreview.lineCount },
      lines: repairImportPreview.lines.map((line) => ({ ...line })),
      returns: [],
    });
    window.location.hash = `/repairs/${encodeURIComponent(repairNo)}`;
    window.setTimeout(() => showToast("返修单创建成功", `${repairNo} 已生成并发送给 ${factory} 工厂。`), 0);
  });
}
