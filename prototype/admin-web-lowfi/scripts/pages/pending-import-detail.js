import { importPendingOrdersAsDrafts, pendingImportData, pendingImportDetailData } from "../mock-data.js";
import { escapeHTML, showToast } from "../components/app-shell.js";
import { getNextSortState, renderSortableHeader, sortRows, updateSortHeaders } from "../components/table-sort.js";

const backIcon = `<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="m15 18-6-6 6-6" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>`;
const factoryOptions = ["宇情", "昱斌", "盛泰", "启宏", "禹帆"];

function formatNumber(value) {
  return new Intl.NumberFormat("zh-CN").format(Number(value) || 0);
}

function getPendingImportDetail(orderNo) {
  const order = pendingImportData.orders.find((item) => item.orderNo === orderNo) ?? pendingImportData.orders[0];
  const detail = pendingImportDetailData[order.orderNo] ?? {
    nearestDue: "2026-08-25",
    totalQuantity: 1200,
    shippedQuantity: 0,
    pendingQuantity: 1200,
    products: [{
      code: "—",
      name: order.productName,
      colorSpec: "待核对",
      factory: order.factory,
      quantity: 1200,
      validationKey: order.validationKey,
      validationLabel: order.validationKey === "ready" ? "通过" : "资料待处理",
    }],
  };
  return {
    ...order,
    ...detail,
    trackers: order.trackers ?? [order.tracker],
    products: detail.products.map((product, index) => ({
      ...product,
      rowKey: index,
      contractShipDate: product.contractShipDate ?? detail.nearestDue,
      shippedQuantity: String(product.shippedQuantity ?? 0),
    })),
  };
}

function renderProductRows(products, editable = false) {
  return products.map((product, index) => {
    const shipped = Number(product.shippedQuantity || 0);
    const pending = Math.max(Number(product.quantity) - shipped, 0);
    const progress = product.quantity ? Math.round(shipped * 100 / product.quantity) : 0;
    const validationTone = product.validationKey === "ready" ? "success" : "warning";
    const factory = editable
      ? `<input class="pending-detail-input pending-factory-input" list="pending-factory-options" value="${escapeHTML(product.factory)}" data-detail-field="factory" aria-label="第${index + 1}条工厂">`
      : escapeHTML(product.factory);
    const contractShipDate = editable
      ? `<input class="pending-detail-input" type="date" value="${escapeHTML(product.contractShipDate)}" data-detail-field="contractShipDate" aria-label="第${index + 1}条合同出货时间">`
      : escapeHTML(product.contractShipDate || "—");
    const shippedQuantity = editable
      ? `<input class="pending-detail-input pending-number-input" type="number" min="0" step="1" value="${escapeHTML(product.shippedQuantity)}" data-detail-field="shippedQuantity" aria-label="第${index + 1}条已发数量">`
      : formatNumber(shipped);
    return `
      <tr data-product-key="${product.rowKey}">
        <td class="detail-sequence-cell">${index + 1}</td>
        <td class="detail-code" title="${escapeHTML(product.code)}">${escapeHTML(product.code)}</td>
        <td><strong class="detail-product-name" title="${escapeHTML(product.name)}">${escapeHTML(product.name)}</strong></td>
        <td>${escapeHTML(product.colorSpec)}</td>
        <td>${factory}</td>
        <td>${contractShipDate}</td>
        <td class="detail-number">${escapeHTML(formatNumber(product.quantity))}</td>
        <td class="detail-number">${shippedQuantity}</td>
        <td class="detail-number" data-pending-quantity>${formatNumber(pending)}</td>
        <td><span class="detail-progress"><span><i style="width: ${Math.min(progress, 100)}%"></i></span><em>${progress}%</em></span></td>
        <td><span class="status-badge is-${validationTone}">${product.validationKey === "ready" ? "通过" : "未通过"}</span></td>
      </tr>
    `;
  }).join("");
}

function productSortValue(product, key) {
  if (key === "shippedQuantity") return Number(product.shippedQuantity || 0);
  if (key === "progress") return product.quantity ? Number(product.shippedQuantity || 0) / product.quantity : 0;
  if (key === "pendingQuantity") return Math.max(product.quantity - Number(product.shippedQuantity || 0), 0);
  return product[key];
}

function renderTrackerTags(trackers) {
  return trackers.map((tracker) => `<span class="tracker-tag" data-tracker="${escapeHTML(tracker)}">${escapeHTML(tracker)}</span>`).join("");
}

function renderConfirmDialog(order) {
  return `
    <div class="detail-confirm-layer" hidden data-import-confirm-layer>
      <button class="detail-confirm-backdrop" type="button" aria-label="取消确认导入为草稿" data-import-confirm-cancel></button>
      <section class="detail-confirm-dialog" role="dialog" aria-modal="true" aria-labelledby="import-confirm-title" aria-describedby="import-confirm-description">
        <h2 id="import-confirm-title">确认导入为草稿</h2>
        <p id="import-confirm-description">确认将候选订单 <strong>${escapeHTML(order.orderNo)}</strong> 导入跟单系统？确认后将在订单列表中生成草稿订单，发布前工厂不可见。</p>
        <div class="detail-confirm-actions">
          <button class="detail-outline-button" type="button" data-import-confirm-cancel>取消</button>
          <button class="detail-primary-button" type="button" data-import-confirm-submit>确认导入为草稿</button>
        </div>
      </section>
    </div>
  `;
}

export function renderPendingImportDetailPage(orderNo) {
  if (!(pendingImportData.orders.some(item => item.orderNo === orderNo))) return `<article class="section-card notification-target-error"><button class="detail-back-button" type="button" data-route="/pending-imports">‹ 返回</button><p class="page-error">内容已不可查看</p></article>`;
  const order = getPendingImportDetail(orderNo);
  const isImported = order.statusKey === "imported";
  const canImport = order.statusKey === "pending" && order.validationKey === "ready";

  return `
    <article class="order-detail-page pending-import-detail-page" data-pending-import-detail-page data-order-no="${escapeHTML(order.orderNo)}">
      <section class="section-card detail-overview-card">
        <header class="detail-page-header">
          <button class="detail-back-button" type="button" data-import-back>${backIcon}<span>返回</span></button>
          <div class="detail-title-row pending-import-detail-actions">
            <span class="status-badge is-${isImported ? "success" : escapeHTML(order.tone)}">${isImported ? "已导入" : escapeHTML(order.validationLabel)}</span>
            ${isImported ? "" : `<button class="detail-primary-button" type="button" data-import-confirm-open ${canImport ? "" : "disabled"} title="${canImport ? "确认导入当前候选为草稿" : "请先处理全部待处理资料"}">确认导入为草稿</button>`}
          </div>
        </header>

        <div class="detail-overview-content">
          <dl class="detail-summary-grid" aria-label="待导入订单概览">
            <div><dt>分类</dt><dd><span class="category-tag is-${order.category === "帽子" ? "hat" : "clothing"}">${escapeHTML(order.category)}</span></dd></div>
            <div><dt>跟单人员</dt><dd>${renderTrackerTags(order.trackers)}</dd></div>
            <div><dt>合同出货时间</dt><dd class="detail-due-date" data-summary-due>${escapeHTML(order.nearestDue)}</dd></div>
            <div><dt>订单数量</dt><dd class="detail-summary-number">${escapeHTML(formatNumber(order.totalQuantity))}</dd></div>
            <div><dt>已发数量</dt><dd class="detail-summary-number" data-summary-shipped>${escapeHTML(formatNumber(order.shippedQuantity))}</dd></div>
            <div><dt>未发数量</dt><dd class="detail-summary-number" data-summary-pending>${escapeHTML(formatNumber(order.pendingQuantity))}</dd></div>
          </dl>
        </div>
      </section>

      <section class="section-card detail-section-card">
        <header class="detail-section-header">
          <h2>订单明细</h2>
          ${isImported ? "" : `<div class="pending-import-save-actions"><span data-unsaved-tip hidden>有未保存修改</span><button class="detail-primary-button" type="button" data-save-details disabled>保存</button></div>`}
        </header>
        <div class="detail-table-scroll">
          <table class="detail-data-table product-detail-table pending-import-detail-table data-grid-table" data-sort-table="pending-products">
            <thead><tr><th class="detail-sequence-column" scope="col">序号</th>${renderSortableHeader("产品编码", "code")}${renderSortableHeader("产品名称", "name")}${renderSortableHeader("颜色/规格", "colorSpec")}${renderSortableHeader("工厂", "factory")}${renderSortableHeader("合同出货时间", "contractShipDate")}${renderSortableHeader("下单数量", "quantity")}${renderSortableHeader("已发数量", "shippedQuantity")}${renderSortableHeader("未发数量", "pendingQuantity")}${renderSortableHeader("发货进度", "progress")}${renderSortableHeader("校验结果", "validationLabel")}</tr></thead>
            <tbody data-pending-products-body>${renderProductRows(order.products, !isImported)}</tbody>
          </table>
          <datalist id="pending-factory-options">${factoryOptions.map((factory) => `<option value="${escapeHTML(factory)}"></option>`).join("")}</datalist>
        </div>
      </section>
      <section class="section-card detail-section-card pending-import-audit-card">
        <header class="detail-section-header"><h2>操作记录</h2></header>
        <div class="pending-import-audit-list" data-candidate-audit>
          <div><strong>系统</strong><span>从飞书获取候选订单资料</span><time>2026-08-20 09:30</time></div>
        </div>
      </section>
      ${renderConfirmDialog(order)}
    </article>
  `;
}

export function bindPendingImportDetailPage(orderNo) {
  const page = document.querySelector("[data-pending-import-detail-page]");
  if (!page) return;
  const layer = page?.querySelector("[data-import-confirm-layer]");
  const openButton = page?.querySelector("[data-import-confirm-open]");
  const order = getPendingImportDetail(orderNo);
  const products = order.products;
  let savedValues = products.map(({ factory, contractShipDate, shippedQuantity }) => ({ factory, contractShipDate, shippedQuantity }));
  let sortState = { key: "code", direction: "asc" };

  const isDirty = () => products.some((product, index) => {
    const saved = savedValues[index];
    return product.factory !== saved.factory || product.contractShipDate !== saved.contractShipDate || product.shippedQuantity !== saved.shippedQuantity;
  });

  const updateDirtyState = () => {
    const dirty = isDirty();
    const saveButton = page.querySelector("[data-save-details]");
    const tip = page.querySelector("[data-unsaved-tip]");
    if (saveButton) saveButton.disabled = !dirty;
    if (tip) tip.hidden = !dirty;
    if (openButton) {
      openButton.disabled = !canImport || dirty;
      openButton.title = dirty ? "请先保存订单明细" : (canImport ? "确认导入当前候选为草稿" : "请先处理全部待处理资料");
    }
  };

  const updateRowQuantity = (row, product) => {
    const shipped = Number(product.shippedQuantity || 0);
    const pending = Math.max(product.quantity - shipped, 0);
    const progress = product.quantity ? Math.round(shipped * 100 / product.quantity) : 0;
    row.querySelector("[data-pending-quantity]").textContent = formatNumber(pending);
    row.querySelector(".detail-progress i").style.width = `${Math.min(progress, 100)}%`;
    row.querySelector(".detail-progress em").textContent = `${progress}%`;
  };

  const closeDialog = () => {
    if (layer) layer.hidden = true;
    document.body.classList.remove("has-dialog-open");
    openButton?.focus();
  };

  page?.querySelector("[data-import-back]")?.addEventListener("click", () => { window.location.hash = "/pending-imports"; });
  openButton?.addEventListener("click", () => {
    if (openButton.disabled || !layer) return;
    layer.hidden = false;
    document.body.classList.add("has-dialog-open");
    layer.querySelector("[data-import-confirm-submit]")?.focus();
  });
  page.querySelector("[data-pending-products-body]")?.addEventListener("input", (event) => {
    const input = event.target.closest("[data-detail-field]");
    const row = input?.closest("[data-product-key]");
    if (!input || !row) return;
    const product = products.find((item) => item.rowKey === Number(row.dataset.productKey));
    if (!product) return;
    product[input.dataset.detailField] = input.value;
    if (input.dataset.detailField === "shippedQuantity") updateRowQuantity(row, product);
    updateDirtyState();
  });
  page.querySelector("[data-save-details]")?.addEventListener("click", () => {
    const invalidFactory = products.find((product) => !factoryOptions.includes(product.factory));
    const invalidQuantity = products.find((product) => product.shippedQuantity === "" || !Number.isInteger(Number(product.shippedQuantity)) || Number(product.shippedQuantity) < 0);
    if (invalidFactory || invalidQuantity) {
      showToast("订单明细保存失败", invalidFactory ? "请选择已有工厂。" : "已发数量必须为非负整数。");
      return;
    }
    const shipped = products.reduce((total, product) => total + Number(product.shippedQuantity), 0);
    const pending = products.reduce((total, product) => total + Math.max(product.quantity - Number(product.shippedQuantity), 0), 0);
    const dates = products.map((product) => product.contractShipDate).filter(Boolean).sort();
    page.querySelector("[data-summary-shipped]").textContent = formatNumber(shipped);
    page.querySelector("[data-summary-pending]").textContent = formatNumber(pending);
    page.querySelector("[data-summary-due]").textContent = dates[0] || "—";
    savedValues = products.map(({ factory, contractShipDate, shippedQuantity }) => ({ factory, contractShipDate, shippedQuantity }));
    const audit = page.querySelector("[data-candidate-audit]");
    if (audit) audit.insertAdjacentHTML("afterbegin", `<div><strong>煎饼</strong><span>修改订单明细：工厂、合同出货时间、已发数量</span><time>刚刚</time></div>`);
    updateDirtyState();
    showToast("订单明细保存成功", `${orderNo} 的修改已保存。`);
  });
  page?.querySelectorAll("[data-import-confirm-cancel]").forEach((button) => button.addEventListener("click", closeDialog));
  page?.querySelector("[data-import-confirm-submit]")?.addEventListener("click", () => {
    importPendingOrdersAsDrafts([orderNo]);

    if (layer) layer.hidden = true;
    document.body.classList.remove("has-dialog-open");
    window.location.hash = "/pending-imports";
    window.setTimeout(() => {
      showToast("确认导入为草稿成功", `${orderNo} 已生成草稿订单。`);
    }, 50);
  });
  page?.addEventListener("click", (event) => {
    const nextSortState = getNextSortState(event, sortState);
    if (!nextSortState) return;
    sortState = nextSortState;
    const table = event.target.closest("[data-sort-table]");
    updateSortHeaders(table, sortState);
    const body = page.querySelector("[data-pending-products-body]");
    if (body) body.innerHTML = renderProductRows(sortRows(products, sortState, productSortValue), order.statusKey !== "imported");
  });
  updateSortHeaders(page, sortState);
  const initialBody = page?.querySelector("[data-pending-products-body]");
  if (initialBody) initialBody.innerHTML = renderProductRows(sortRows(products, sortState, productSortValue), order.statusKey !== "imported");
  page?.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && layer && !layer.hidden) closeDialog();
  });
}
