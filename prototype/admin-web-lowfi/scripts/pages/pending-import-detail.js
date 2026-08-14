import { importPendingOrdersAsDrafts, pendingImportData, pendingImportDetailData } from "../mock-data.js";
import { escapeHTML, showToast } from "../components/app-shell.js";

const backIcon = `<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="m15 18-6-6 6-6" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>`;
const productIcon = `<svg viewBox="0 0 28 34" fill="none" aria-hidden="true"><path d="m9 5 5-2 5 2 5 6-4 3v15H8V14l-4-3 5-6Z" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"/><path d="M11 5c.6 2 1.6 3 3 3s2.4-1 3-3" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/></svg>`;

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
  return { ...order, ...detail };
}

function renderProductRows(products) {
  return products.map((product, index) => {
    const validationTone = product.validationKey === "ready" ? "success" : "warning";
    return `
      <tr>
        <td class="detail-sequence">${index + 1}</td>
        <td><span class="product-thumb" aria-label="产品图片未上传">${productIcon}</span></td>
        <td class="detail-code">${escapeHTML(product.code)}</td>
        <td><strong class="detail-product-name">${escapeHTML(product.name)}</strong></td>
        <td>${escapeHTML(product.colorSpec)}</td>
        <td>${escapeHTML(product.factory)}</td>
        <td class="detail-number">${escapeHTML(formatNumber(product.quantity))}</td>
        <td class="detail-number">0</td>
        <td class="detail-number">${escapeHTML(formatNumber(product.quantity))}</td>
        <td><div class="detail-shipping-progress"><span class="progress-track" aria-label="发货进度 0%"><span class="progress-bar" style="width: 0%"></span></span><span>0%</span></div></td>
        <td><span class="status-badge is-${validationTone}">${escapeHTML(product.validationLabel)}</span></td>
      </tr>
    `;
  }).join("");
}

function renderConfirmDialog(order) {
  return `
    <div class="detail-confirm-layer" hidden data-import-confirm-layer>
      <button class="detail-confirm-backdrop" type="button" aria-label="取消确认导入" data-import-confirm-cancel></button>
      <section class="detail-confirm-dialog" role="dialog" aria-modal="true" aria-labelledby="import-confirm-title" aria-describedby="import-confirm-description">
        <h2 id="import-confirm-title">确认导入订单</h2>
        <p id="import-confirm-description">确认将订单 <strong>${escapeHTML(order.orderNo)}</strong> 导入跟单系统？导入后将在订单列表中生成正式草稿订单。</p>
        <div class="detail-confirm-actions">
          <button class="detail-outline-button" type="button" data-import-confirm-cancel>取消</button>
          <button class="detail-primary-button" type="button" data-import-confirm-submit>确认导入</button>
        </div>
      </section>
    </div>
  `;
}

export function renderPendingImportDetailPage(orderNo) {
  const order = getPendingImportDetail(orderNo);
  const canImport = order.validationKey === "ready";

  return `
    <article class="order-detail-page pending-import-detail-page" data-pending-import-detail-page data-order-no="${escapeHTML(order.orderNo)}">
      <section class="section-card detail-overview-card">
        <header class="detail-page-header">
          <button class="detail-back-button" type="button" data-import-back>${backIcon}<span>返回</span></button>
          <div class="detail-title-row pending-import-detail-actions">
            <span class="status-badge is-${escapeHTML(order.tone)}">${escapeHTML(order.validationLabel)}</span>
            <button class="detail-primary-button" type="button" data-import-confirm-open ${canImport ? "" : "disabled"} title="${canImport ? "确认导入当前订单" : "请先处理全部待处理资料"}">确认导入</button>
          </div>
        </header>

        <div class="detail-overview-content">
          <dl class="detail-summary-grid" aria-label="待导入订单概览">
            <div><dt>分类</dt><dd><span class="category-tag is-${order.category === "帽子" ? "hat" : "clothing"}">${escapeHTML(order.category)}</span></dd></div>
            <div><dt>跟单人员</dt><dd><span class="tracker-tag" data-tracker="${escapeHTML(order.tracker)}">${escapeHTML(order.tracker)}</span></dd></div>
            <div><dt>最近合同出货时间</dt><dd class="detail-due-date">${escapeHTML(order.nearestDue)}</dd></div>
            <div><dt>订单数量</dt><dd class="detail-summary-number">${escapeHTML(formatNumber(order.totalQuantity))}</dd></div>
            <div><dt>已出数量</dt><dd class="detail-summary-number">${escapeHTML(formatNumber(order.shippedQuantity))}</dd></div>
            <div><dt>未出数量</dt><dd class="detail-summary-number">${escapeHTML(formatNumber(order.pendingQuantity))}</dd></div>
          </dl>
        </div>
      </section>

      <section class="section-card detail-section-card">
        <header class="detail-section-header"><h2>订单明细</h2></header>
        <div class="detail-table-scroll">
          <table class="detail-data-table product-detail-table pending-import-detail-table">
            <thead><tr><th scope="col">序号</th><th scope="col">图片</th><th scope="col">产品编码</th><th scope="col">产品名称</th><th scope="col">颜色/规格</th><th scope="col">工厂</th><th scope="col">下单数量</th><th scope="col">已出数量</th><th scope="col">未出数量</th><th scope="col">发货进度</th><th scope="col">校验结果</th></tr></thead>
            <tbody>${renderProductRows(order.products)}</tbody>
          </table>
        </div>
      </section>
      ${renderConfirmDialog(order)}
    </article>
  `;
}

export function bindPendingImportDetailPage(orderNo) {
  const page = document.querySelector("[data-pending-import-detail-page]");
  const layer = page?.querySelector("[data-import-confirm-layer]");
  const openButton = page?.querySelector("[data-import-confirm-open]");

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
  page?.querySelectorAll("[data-import-confirm-cancel]").forEach((button) => button.addEventListener("click", closeDialog));
  page?.querySelector("[data-import-confirm-submit]")?.addEventListener("click", () => {
    importPendingOrdersAsDrafts([orderNo]);

    if (layer) layer.hidden = true;
    document.body.classList.remove("has-dialog-open");
    window.location.hash = "/pending-imports";
    window.setTimeout(() => {
      showToast("订单导入成功", `${orderNo} 已生成正式草稿订单。`);
    }, 50);
  });
  page?.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && layer && !layer.hidden) closeDialog();
  });
}
