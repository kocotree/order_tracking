import { orderDetailData, orderListData } from "../mock-data.js";
import { escapeHTML, showToast } from "../components/app-shell.js";
import { getNextSortState, renderSortableHeader, sortRows, updateSortHeaders } from "../components/table-sort.js";
import { buildRouteWithReturn, getCurrentLocation, getReturnRoute } from "../router.js";

const backIcon = `<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="m15 18-6-6 6-6" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>`;

function getOrderDisplayStatus(order) {
  if (order.statusKey === "draft") return { label: "草稿", tone: "draft" };
  if (order.statusKey === "completed") return { label: "已完成", tone: "success" };
  if (order.overdueDays > 0) return { label: "已逾期", tone: "danger" };
  return { label: "未完成", tone: "info" };
}

function formatNumber(value) {
  return new Intl.NumberFormat("zh-CN").format(Number(value) || 0);
}

function buildFallbackDetail(orderNo) {
  const sourceOrder = orderListData.orders.find((item) => item.orderNo === orderNo) ?? orderListData.orders[0];
  const factories = sourceOrder.factory.split(/[、,，]/).map((value) => value.trim());
  const totalQuantity = Number(sourceOrder.shippedText.split("/")[1]?.replaceAll(",", "").trim()) || 0;
  const shippedQuantity = Number(sourceOrder.shippedText.split("/")[0]?.replaceAll(",", "").trim()) || 0;

  return {
    ...sourceOrder,
    orderDate: sourceOrder.orderDate,
    source: "飞书多维表格导入",
    statusLabel: getOrderDisplayStatus(sourceOrder).label,
    tone: getOrderDisplayStatus(sourceOrder).tone,
    totalQuantity,
    shippedQuantity,
    pendingQuantity: Math.max(totalQuantity - shippedQuantity, 0),
    remark: "—",
    products: [{
      code: "—",
      name: sourceOrder.productName,
      colorSpec: sourceOrder.specSummary,
      quantity: totalQuantity,
      shippedQuantity,
      pendingQuantity: Math.max(totalQuantity - shippedQuantity, 0),
    }],
    factories: factories.map((factory, index) => ({
      name: factory,
      contractNo: `${sourceOrder.orderDate.replaceAll("-", "")}-KK-${String(index + 1).padStart(2, "0")}`,
      allocated: Math.round(totalQuantity / factories.length),
      shipped: Math.round(shippedQuantity / factories.length),
      statusLabel: getOrderDisplayStatus(sourceOrder).label,
      tone: getOrderDisplayStatus(sourceOrder).tone,
      contractReady: true,
      lines: [
        {
          colorSpec: sourceOrder.specSummary,
          dueDate: sourceOrder.nearestDue,
          quantity: Math.round(totalQuantity / factories.length),
          price: "",
          shipped: Math.round(shippedQuantity / factories.length),
        },
      ],
    })),
    shipments: [],
    logs: [{ time: sourceOrder.updatedAt.replace("T", " ").slice(0, 16), operator: sourceOrder.tracker, action: "更新订单信息", source: "管理员网页端" }],
  };
}

function getOrderDetail(orderNo) {
  const detail = orderDetailData[orderNo] ?? buildFallbackDetail(orderNo);
  const sourceOrder = orderListData.orders.find((item) => item.orderNo === orderNo);
  if (!sourceOrder) return detail;
  const displayStatus = getOrderDisplayStatus(sourceOrder);
  return { ...detail, statusKey: sourceOrder.statusKey, statusLabel: displayStatus.label, tone: displayStatus.tone };
}

function buildProductFactoryRows(order) {
  return order.products.flatMap((product) => {
    const factoryRows = order.factories.flatMap((factory) =>
      factory.lines
        .filter((line) => (!line.code || line.code === product.code) && line.colorSpec === product.colorSpec)
        .map((line) => ({
          ...product,
          factory: factory.name,
          quantity: line.quantity,
          shippedQuantity: line.shipped,
          pendingQuantity: Math.max(line.quantity - line.shipped, 0),
        })),
    );

    return factoryRows.length > 0 ? factoryRows : [{ ...product, factory: "—" }];
  });
}

function renderProductRows(rows) {
  return rows
    .map(
      (product, index) => `
        <tr>
          <td class="detail-sequence-cell">${index + 1}</td>
          <td class="detail-code">${escapeHTML(product.code)}</td>
          <td><strong class="detail-product-name">${escapeHTML(product.name)}</strong></td>
          <td>${escapeHTML(product.colorSpec)}</td>
          <td>${escapeHTML(product.factory)}</td>
          <td class="detail-number">${escapeHTML(formatNumber(product.quantity))}</td>
          <td class="detail-number">${escapeHTML(formatNumber(product.shippedQuantity))}</td>
          <td class="detail-number">${escapeHTML(formatNumber(product.pendingQuantity))}</td>
          <td>
            <span class="detail-progress"><span><i style="width: ${product.quantity ? Math.round(product.shippedQuantity / product.quantity * 100) : 0}%"></i></span><em>${product.quantity ? Math.round(product.shippedQuantity / product.quantity * 100) : 0}%</em></span>
          </td>
        </tr>
      `,
    )
    .join("");
}

function renderShipmentRows(shipments) {
  if (!shipments.length) return '<tr><td colspan="6" class="detail-empty-row">当前订单暂无关联发货单</td></tr>';
  return shipments.map(item => `<tr><td><button class="row-link" type="button" data-shipment-detail="${escapeHTML(item.no)}">${escapeHTML(item.no)}</button></td><td>${escapeHTML(item.shipDate)}</td><td>${formatNumber(item.declared)}</td><td>—</td><td>${escapeHTML(item.statusLabel)}</td><td><button class="row-link" type="button" data-shipment-detail="${escapeHTML(item.no)}">详情</button></td></tr>`).join("");
}

function productSortValue(product, key) {
  if (key === "progress") return product.quantity ? product.shippedQuantity / product.quantity : 0;
  return product[key];
}

function shipmentSortValue(shipment, key) {
  return shipment[key];
}

function renderPublishDialog(order) {
  return `
    <div class="modal-backdrop" hidden data-publish-confirm-layer>
      <section class="modal action-modal" role="dialog" aria-modal="true" aria-labelledby="publish-confirm-title" aria-describedby="publish-confirm-description">
        <header><h2 id="publish-confirm-title">发布订单</h2><button type="button" data-publish-confirm-cancel>×</button></header><div class="modal-body">
        <p id="publish-confirm-description">确认发布订单 <strong>${escapeHTML(order.orderNo)}</strong>？发布后相关工厂将在小程序收到任务，订单状态将变为未完成。</p>
        </div><footer>
          <button class="order-secondary-button" type="button" data-publish-confirm-cancel>取消</button>
          <button class="order-primary-button" type="button" data-publish-confirm-submit>确认</button>
        </footer>
      </section>
    </div>
  `;
}

function renderCompleteDialog(order) {
  return `
    <div class="modal-backdrop" hidden data-complete-confirm-layer>
      <section class="modal action-modal" role="dialog" aria-modal="true" aria-labelledby="complete-confirm-title" aria-describedby="complete-confirm-description">
        <header><h2 id="complete-confirm-title">确认订单完成</h2><button type="button" data-complete-confirm-cancel>×</button></header><div class="modal-body">
        <p id="complete-confirm-description">请核对数量摘要。完成状态不会根据发货数量自动产生。</p>
        <dl class="completion-summary">
          <div><dt>订单数量</dt><dd>${escapeHTML(formatNumber(order.totalQuantity))}</dd></div>
          <div><dt>已发数量</dt><dd>${escapeHTML(formatNumber(order.shippedQuantity))}</dd></div>
          <div><dt>未发数量</dt><dd>${escapeHTML(formatNumber(order.pendingQuantity))}</dd></div>
        </dl>
        </div><footer>
          <button class="order-secondary-button" type="button" data-complete-confirm-cancel>取消</button>
          <button class="order-primary-button" type="button" data-complete-confirm-submit>确认</button>
        </footer>
      </section>
    </div>
  `;
}

function renderReopenDialog(order) {
  return `
    <div class="modal-backdrop" hidden data-reopen-confirm-layer>
      <section class="modal action-modal" role="dialog" aria-modal="true" aria-labelledby="reopen-confirm-title" aria-describedby="reopen-confirm-description">
        <header><h2 id="reopen-confirm-title">撤销完成</h2><button type="button" data-reopen-confirm-cancel>×</button></header><div class="modal-body">
        <p id="reopen-confirm-description">订单 <strong>${escapeHTML(order.orderNo)}</strong> 将恢复为未完成；若已超过合同出货时间，则显示为已逾期。</p>
        <label class="reopen-field">
          <span>撤销原因</span>
          <textarea maxlength="500" placeholder="请输入撤销原因" data-reopen-reason></textarea>
        </label>
        <p class="order-reopen-error" hidden data-reopen-error>请填写撤销原因。</p>
        </div><footer>
          <button class="order-secondary-button" type="button" data-reopen-confirm-cancel>取消</button>
          <button class="order-primary-button" type="button" data-reopen-confirm-submit>确认</button>
        </footer>
      </section>
    </div>
  `;
}

function getContractSigningDate(factory) {
  if (factory.contractSignDate) return factory.contractSignDate;
  const match = String(factory.contractNo ?? "").match(/^(\d{4})(\d{2})(\d{2})/);
  if (match) return `${match[1]}-${match[2]}-${match[3]}`;
  const today = new Date();
  const year = today.getFullYear();
  const month = String(today.getMonth() + 1).padStart(2, "0");
  const day = String(today.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function hasExportedContract(factory) {
  return Boolean(factory.contractNo && factory.contractNo !== "—");
}

function renderContractConfirmDialog(order, factory) {
  const exported = hasExportedContract(factory);
  const signingDate = getContractSigningDate(factory);
  return `
    <section class="modal contract-export-dialog" role="dialog" aria-modal="true" aria-labelledby="contract-export-title">
      <header class="contract-export-header">
        <h2 id="contract-export-title">导出加工合同</h2>
        <button class="contract-export-close" type="button" aria-label="关闭导出加工合同弹窗" data-contract-export-close>×</button>
      </header>
      <div class="contract-export-body">
        <dl class="contract-export-summary">
          <div><dt>订单编号</dt><dd>${escapeHTML(order.orderNo)}</dd></div>
          <div><dt>工厂</dt><dd>${escapeHTML(factory.name)}</dd></div>
          <div><dt>合同资料</dt><dd><span class="contract-ready-badge is-${factory.contractReady ? "ready" : "missing"}">${factory.contractReady ? "完整" : "待补充"}</span></dd></div>
          <div><dt>合同编号</dt><dd>${exported ? escapeHTML(factory.contractNo) : "首次导出后生成"}</dd></div>
        </dl>
        <label class="contract-date-field">
          <span>签订日期</span>
          <input type="date" value="${escapeHTML(signingDate)}" data-contract-signing-date ${exported ? "readonly" : ""} />
        </label>
        ${exported ? '<p class="contract-repeat-hint">将按首次合同快照重新生成，合同编号和签订日期不变。</p>' : ""}
        ${factory.contractReady ? "" : `<p class="contract-export-warning">该工厂的合同资料不完整，暂不能导出。请先在工厂资料中补全工厂代码、单位全称、单位地址和法定代表人。</p>`}
      </div>
      <footer>
        <button class="order-secondary-button" type="button" data-contract-export-close>取消</button>
        <button class="order-primary-button" type="button" data-contract-export-submit="${escapeHTML(factory.name)}" ${factory.contractReady ? "" : "disabled"}>确认导出</button>
      </footer>
    </section>
  `;
}

function renderContractFactoryListDialog(order) {
  const rows = order.factories.map((factory) => {
    const exported = hasExportedContract(factory);
    return `
      <tr>
        <td><strong>${escapeHTML(factory.name)}</strong></td>
        <td><span class="contract-ready-badge is-${factory.contractReady ? "ready" : "missing"}">${factory.contractReady ? "完整" : "待补充"}</span></td>
        <td>${exported ? escapeHTML(factory.contractNo) : "首次导出后生成"}</td>
        <td>${escapeHTML(getContractSigningDate(factory))}</td>
        <td><button class="detail-text-button" type="button" data-contract-select-factory="${escapeHTML(factory.name)}" ${factory.contractReady ? "" : "disabled"}>导出</button></td>
      </tr>
    `;
  }).join("");

  return `
    <section class="modal contract-export-dialog is-factory-list" role="dialog" aria-modal="true" aria-labelledby="contract-export-title">
      <header class="contract-export-header">
        <h2 id="contract-export-title">导出加工合同</h2>
        <button class="contract-export-close" type="button" aria-label="关闭导出加工合同弹窗" data-contract-export-close>×</button>
      </header>
      <div class="contract-export-body">
        <p class="contract-export-intro">订单 ${escapeHTML(order.orderNo)} 包含多个工厂，请选择需要导出合同的工厂。</p>
        <div class="contract-factory-table-wrap">
          <table class="contract-factory-table">
            <thead><tr><th>工厂</th><th>合同资料</th><th>合同编号</th><th>签订日期</th><th>操作</th></tr></thead>
            <tbody>${rows}</tbody>
          </table>
        </div>
      </div>
    </section>
  `;
}

function renderContractExportLayer(order) {
  const dialog = order.factories.length === 1
    ? renderContractConfirmDialog(order, order.factories[0])
    : renderContractFactoryListDialog(order);
  return `
    <div class="detail-confirm-layer" hidden data-contract-export-layer>
      <button class="detail-confirm-backdrop" type="button" aria-label="取消导出加工合同" data-contract-export-close></button>
      <div class="contract-export-dialog-root" data-contract-export-dialog-root>${dialog}</div>
    </div>
  `;
}

export function renderOrderDetailPage(orderNo) {
  if (!(orderListData.orders.some(item => item.orderNo === orderNo))) return `<article class="section-card notification-target-error"><button class="detail-back-button" type="button" data-route="/orders">‹ 返回</button><p class="page-error">内容已不可查看</p></article>`;
  const order = getOrderDetail(orderNo);
  const productFactoryRows = buildProductFactoryRows(order);
  const isDraft = order.statusKey === "draft";
  const isCompleted = order.statusKey === "completed";
  const canComplete = !isDraft && !isCompleted;
  const canExportContract = !isDraft && !isCompleted && order.factories.length > 0 && Number(order.shippedQuantity) === 0;

  return `
    <article class="order-workspace order-detail-page" data-order-detail-page data-order-no="${escapeHTML(order.orderNo)}">
      <section class="section-card detail-overview-card">
        <header class="detail-page-header">
          <button class="detail-back-button" type="button" data-order-back>${backIcon}<span>返回</span></button>
          <div class="detail-title-row order-detail-actions">
            <span class="status-badge is-${escapeHTML(order.tone)}"><i aria-hidden="true"></i>${escapeHTML(order.statusLabel)}</span>
            ${isDraft ? `<button class="detail-primary-button" type="button" data-publish-confirm-open>发布订单</button>` : ""}
            <button class="detail-outline-button" type="button" data-contract-export-open ${canExportContract ? "" : "disabled"} title="${canExportContract ? "导出加工合同" : isDraft ? "请先发布订单后再导出加工合同" : "只有已发布且已发数量为0的订单才能导出加工合同"}">导出加工合同</button>
            ${canComplete ? `<button class="detail-outline-button" type="button" data-withdraw-open>撤回订单</button>` : ""}
            ${canComplete ? `<button class="detail-primary-button" type="button" data-complete-confirm-open>确认订单完成</button>` : ""}
            ${isCompleted ? `<button class="detail-outline-button" type="button" data-reopen-confirm-open>撤销完成</button>` : ""}
          </div>
        </header>

        <div class="detail-overview-content">
          <dl class="detail-summary-grid" aria-label="订单概览">
            <div><dt>分类</dt><dd><span class="category-tag is-${order.category === "帽子" ? "hat" : "clothing"}">${escapeHTML(order.category)}</span></dd></div>
            <div><dt>跟单人员</dt><dd><span class="tracker-tag" data-tracker="${escapeHTML(order.tracker)}">${escapeHTML(order.tracker)}</span></dd></div>
            <div><dt>合同出货时间</dt><dd class="detail-due-date">${escapeHTML(order.nearestDue)}</dd></div>
            <div><dt>订单数量</dt><dd class="detail-summary-number">${escapeHTML(formatNumber(order.totalQuantity))}</dd></div>
            <div><dt>已发数量</dt><dd class="detail-summary-number">${escapeHTML(formatNumber(order.shippedQuantity))}</dd></div>
            <div><dt>未发数量</dt><dd class="detail-summary-number">${escapeHTML(formatNumber(order.pendingQuantity))}</dd></div>
          </dl>
        </div>
      </section>

      <section class="section-card detail-section-card">
        <header class="detail-section-header">
          <h2>订单明细</h2>
        </header>
        <div class="detail-table-scroll">
          <table class="detail-data-table product-detail-table data-grid-table" data-sort-table="order-products">
            <thead>
              <tr>
                <th class="detail-sequence-column" scope="col">序号</th>
                ${renderSortableHeader("产品编码", "code")}
                ${renderSortableHeader("产品名称", "name")}
                ${renderSortableHeader("颜色/规格", "colorSpec")}
                ${renderSortableHeader("工厂", "factory")}
                ${renderSortableHeader("下单数量", "quantity")}
                ${renderSortableHeader("已发数量", "shippedQuantity")}
                ${renderSortableHeader("未发数量", "pendingQuantity")}
                ${renderSortableHeader("发货进度", "progress")}
              </tr>
            </thead>
            <tbody data-order-products-body>${renderProductRows(productFactoryRows)}</tbody>
          </table>
        </div>
      </section>

      <section class="section-card detail-section-card">
        <header class="detail-section-header">
          <h2>关联发货单</h2>
        </header>
        <div class="detail-table-scroll">
          <table class="detail-data-table related-shipment-table data-grid-table"><thead><tr><th>发货单号</th><th>发货日期</th><th>发货数量</th><th>物流单号</th><th>状态</th><th>操作</th></tr></thead><tbody data-order-shipments-body>${renderShipmentRows(order.shipments)}</tbody>
          </table>
        </div>
      </section>
      <section class="section-card detail-section-card order-audit-card">
        <button class="order-audit-toggle" type="button" aria-expanded="false" data-order-audit-toggle ${order.logs?.length ? "" : "disabled"}><span class="order-audit-toggle-title">操作记录<em>（${order.logs?.length || 0}）</em></span><span class="order-audit-toggle-action" data-audit-label>${order.logs?.length ? "展开" : "暂无记录"}</span></button>
        <ol class="order-audit-list shipment-log-list" hidden data-order-audit-list>${(order.logs || []).map(log => `<li class="shipment-log-item"><span class="shipment-log-dot"></span><div><strong>${escapeHTML(log.action)}</strong><span>${escapeHTML(log.time)} · ${escapeHTML(log.operator)} · ${escapeHTML(log.source || "系统")}</span></div></li>`).join("")}</ol>
      </section>
      ${canComplete ? `<div class="modal-backdrop" hidden data-withdraw-layer><section class="modal action-modal" role="dialog" aria-modal="true"><header><h2>撤回订单</h2><button type="button" data-withdraw-cancel>×</button></header><div class="modal-body"><p>撤回后订单恢复为草稿，工厂任务将不可见。</p><p class="page-error" hidden data-withdraw-error></p></div><footer><button class="order-secondary-button" data-withdraw-cancel type="button">取消</button><button class="order-primary-button" data-withdraw-confirm type="button">确认</button></footer></section></div>` : ""}
      ${isDraft ? renderPublishDialog(order) : ""}
      ${canComplete ? renderCompleteDialog(order) : ""}
      ${isCompleted ? renderReopenDialog(order) : ""}
      ${renderContractExportLayer(order)}
    </article>
  `;
}

export function bindOrderDetailPage(orderNo) {
  const page = document.querySelector("[data-order-detail-page]");
  if (!page) return;
  const publishLayer = page?.querySelector("[data-publish-confirm-layer]");
  const publishButton = page?.querySelector("[data-publish-confirm-open]");
  const completeLayer = page?.querySelector("[data-complete-confirm-layer]");
  const completeButton = page?.querySelector("[data-complete-confirm-open]");
  const reopenLayer = page?.querySelector("[data-reopen-confirm-layer]");
  const reopenButton = page?.querySelector("[data-reopen-confirm-open]");
  const contractLayer = page?.querySelector("[data-contract-export-layer]");
  const contractButton = page?.querySelector("[data-contract-export-open]");
  const contractDialogRoot = page?.querySelector("[data-contract-export-dialog-root]");
  const order = getOrderDetail(orderNo);
  const productRows = buildProductFactoryRows(order);
  const sortStates = {
    "order-products": { key: null, direction: "asc" },
    "order-shipments": { key: null, direction: "asc" },
  };

  const closePublishDialog = () => {
    if (publishLayer) publishLayer.hidden = true;
    document.body.classList.remove("has-dialog-open");
    publishButton?.focus();
  };

  const closeContractDialog = () => {
    if (contractLayer) contractLayer.hidden = true;
    document.body.classList.remove("has-dialog-open");
    contractButton?.focus();
  };

  const closeCompleteDialog = () => {
    if (completeLayer) completeLayer.hidden = true;
    document.body.classList.remove("has-dialog-open");
    completeButton?.focus();
  };

  const closeReopenDialog = () => {
    if (reopenLayer) reopenLayer.hidden = true;
    document.body.classList.remove("has-dialog-open");
    reopenButton?.focus();
  };

  const refreshOrderDetail = () => {
    window.dispatchEvent(new Event("hashchange"));
  };

  page?.querySelector("[data-order-audit-toggle]")?.addEventListener("click", event => {
    const list = page.querySelector("[data-order-audit-list]");
    list.hidden = !list.hidden;
    event.currentTarget.setAttribute("aria-expanded", String(!list.hidden));
    page.querySelector("[data-audit-label]").textContent = list.hidden ? "展开" : "收起";
  });
  const withdrawLayer = page?.querySelector("[data-withdraw-layer]");
  page?.querySelector("[data-withdraw-open]")?.addEventListener("click", () => { withdrawLayer.hidden = false; });
  page?.querySelectorAll("[data-withdraw-cancel]").forEach(button => button.addEventListener("click", () => { withdrawLayer.hidden = true; }));
  page?.querySelector("[data-withdraw-confirm]")?.addEventListener("click", () => {
    if (order.shipments?.length || order.shippedQuantity > 0) { const error = page.querySelector("[data-withdraw-error]"); error.hidden = false; error.textContent = "订单已产生发货记录，不能撤回"; return; }
    const source = orderListData.orders.find(item => item.orderNo === orderNo);
    if (source) Object.assign(source, { statusKey: "draft", statusLabel: "草稿", tone: "draft" });
    if (orderDetailData[orderNo]) { Object.assign(orderDetailData[orderNo], { statusKey: "draft", statusLabel: "草稿", tone: "draft" }); orderDetailData[orderNo].logs.unshift({ time: new Date().toLocaleString("zh-CN"), operator: "煎饼", action: "撤回订单", source: "管理员网页" }); }
    refreshOrderDetail();
  });
  page?.querySelector("[data-order-back]")?.addEventListener("click", () => {
    window.location.hash = getReturnRoute("/orders");
  });

  publishButton?.addEventListener("click", () => {
    if (!publishLayer) return;
    publishLayer.hidden = false;
    document.body.classList.add("has-dialog-open");
    publishLayer.querySelector("[data-publish-confirm-submit]")?.focus();
  });

  completeButton?.addEventListener("click", () => {
    if (!completeLayer) return;
    completeLayer.hidden = false;
    document.body.classList.add("has-dialog-open");
    completeLayer.querySelector("[data-complete-confirm-submit]")?.focus();
  });

  reopenButton?.addEventListener("click", () => {
    if (!reopenLayer) return;
    reopenLayer.hidden = false;
    document.body.classList.add("has-dialog-open");
    reopenLayer.querySelector("[data-reopen-reason]")?.focus();
  });

  contractButton?.addEventListener("click", () => {
    if (!contractLayer) return;
    if (Number(order.shippedQuantity) !== 0) {
      showToast("无法导出", "只有已发数量为0的订单才能导出加工合同。");
      return;
    }
    if (contractDialogRoot) {
      contractDialogRoot.innerHTML = order.factories.length === 1
        ? renderContractConfirmDialog(order, order.factories[0])
        : renderContractFactoryListDialog(order);
    }
    contractLayer.hidden = false;
    document.body.classList.add("has-dialog-open");
    contractLayer.querySelector("[data-contract-select-factory], [data-contract-export-submit], [data-contract-export-close]")?.focus();
  });

  page?.querySelectorAll("[data-publish-confirm-cancel]").forEach((button) => {
    button.addEventListener("click", closePublishDialog);
  });

  page?.querySelectorAll("[data-complete-confirm-cancel]").forEach((button) => {
    button.addEventListener("click", closeCompleteDialog);
  });

  page?.querySelectorAll("[data-reopen-confirm-cancel]").forEach((button) => {
    button.addEventListener("click", closeReopenDialog);
  });

  page?.querySelector("[data-publish-confirm-submit]")?.addEventListener("click", () => {
    const sourceOrder = orderListData.orders.find((item) => item.orderNo === orderNo);
    if (sourceOrder) {
      sourceOrder.statusKey = "pending";
      sourceOrder.statusLabel = "未完成";
      sourceOrder.tone = "info";
      sourceOrder.updatedAt = new Date().toISOString();
    }

    const detailOrder = orderDetailData[orderNo];
    if (detailOrder) {
      detailOrder.statusKey = "pending";
      detailOrder.statusLabel = "未完成";
      detailOrder.tone = "info";
    }

    if (publishLayer) publishLayer.remove();
    document.body.classList.remove("has-dialog-open");
    const statusBadge = page?.querySelector(".order-detail-actions .status-badge");
    if (statusBadge) {
      statusBadge.className = "status-badge is-info";
      statusBadge.textContent = "未完成";
    }
    publishButton?.remove();
    refreshOrderDetail();
    showToast("订单发布成功", `${orderNo} 已变为未完成，相关工厂将收到任务。`);
  });

  page?.querySelector("[data-complete-confirm-submit]")?.addEventListener("click", () => {
    const sourceOrder = orderListData.orders.find((item) => item.orderNo === orderNo);
    const detailOrder = orderDetailData[orderNo];
    if (sourceOrder) {
      sourceOrder.statusKey = "completed";
      sourceOrder.statusLabel = "已完成";
      sourceOrder.tone = "success";
      sourceOrder.updatedAt = new Date().toISOString();
    }
    if (detailOrder) {
      detailOrder.statusKey = "completed";
      detailOrder.statusLabel = "已完成";
      detailOrder.tone = "success";
      detailOrder.logs?.unshift({ time: new Date().toLocaleString("zh-CN", { hour12: false }).slice(0, 16), operator: "煎饼", action: "确认订单完成", source: "管理员网页端" });
    }
    closeCompleteDialog();
    refreshOrderDetail();
    showToast("订单已完成", `${orderNo} 已标记为已完成。`);
  });

  page?.querySelector("[data-reopen-confirm-submit]")?.addEventListener("click", () => {
    const reasonInput = reopenLayer?.querySelector("[data-reopen-reason]");
    const error = reopenLayer?.querySelector("[data-reopen-error]");
    const reason = reasonInput?.value.trim() ?? "";
    if (!reason) {
      if (error) error.hidden = false;
      reasonInput?.setAttribute("aria-invalid", "true");
      reasonInput?.focus();
      return;
    }

    const sourceOrder = orderListData.orders.find((item) => item.orderNo === orderNo);
    const detailOrder = orderDetailData[orderNo];
    const dueDate = sourceOrder?.nearestDue ?? order.nearestDue;
    const today = new Date().toISOString().slice(0, 10);
    const isOverdue = dueDate < today;
    if (sourceOrder) {
      sourceOrder.statusKey = "pending";
      sourceOrder.statusLabel = isOverdue ? "已逾期" : "未完成";
      sourceOrder.tone = isOverdue ? "danger" : "info";
      sourceOrder.overdueDays = isOverdue ? Math.max(1, Math.floor((new Date(today) - new Date(dueDate)) / 86400000)) : 0;
      sourceOrder.updatedAt = new Date().toISOString();
    }
    if (detailOrder) {
      detailOrder.statusKey = "pending";
      detailOrder.statusLabel = isOverdue ? "已逾期" : "未完成";
      detailOrder.tone = isOverdue ? "danger" : "info";
      detailOrder.logs?.unshift({ time: new Date().toLocaleString("zh-CN", { hour12: false }).slice(0, 16), operator: "煎饼", action: `撤销完成：${reason}`, source: "管理员网页端" });
    }
    closeReopenDialog();
    refreshOrderDetail();
    showToast("已撤销完成", `${orderNo} 已恢复为${isOverdue ? "已逾期" : "未完成"}。`);
  });

  page?.addEventListener("click", (event) => {
    if (event.target.closest("[data-contract-export-close]")) {
      closeContractDialog();
      return;
    }

    const selectedFactoryName = event.target.closest("[data-contract-select-factory]")?.dataset.contractSelectFactory;
    if (selectedFactoryName && contractDialogRoot) {
      const factory = order.factories.find((item) => item.name === selectedFactoryName);
      if (factory) {
        contractDialogRoot.innerHTML = renderContractConfirmDialog(order, factory);
        contractDialogRoot.querySelector("[data-contract-export-submit], [data-contract-export-close]")?.focus();
      }
      return;
    }

    const exportFactoryName = event.target.closest("[data-contract-export-submit]")?.dataset.contractExportSubmit;
    if (exportFactoryName) {
      if (Number(order.shippedQuantity) !== 0) {
        closeContractDialog();
        showToast("无法导出", "该订单已经产生发货记录，不能导出加工合同。");
        return;
      }
      const factory = order.factories.find((item) => item.name === exportFactoryName);
      if (!factory?.contractReady) return;
      const signingDate = contractDialogRoot?.querySelector("[data-contract-signing-date]")?.value;
      if (!signingDate) {
        showToast("无法导出", "请先填写合同签订日期。");
        return;
      }
      factory.contractSignDate = signingDate;
      closeContractDialog();
      showToast("合同已生成", `${orderNo} · ${factory.name} 的加工合同 Excel 已生成。`);
      return;
    }

    const sortTable = event.target.closest("[data-sort-key]")?.closest("[data-sort-table]");
    const sortScope = sortTable?.dataset.sortTable;
    if (sortScope && sortStates[sortScope]) {
      const nextSortState = getNextSortState(event, sortStates[sortScope]);
      sortStates[sortScope] = nextSortState;
      updateSortHeaders(sortTable, nextSortState);
      if (sortScope === "order-products") {
        const body = page.querySelector("[data-order-products-body]");
        if (body) body.innerHTML = renderProductRows(sortRows(productRows, nextSortState, productSortValue));
      } else {
        const body = page.querySelector("[data-order-shipments-body]");
        if (body) body.innerHTML = renderShipmentRows(sortRows(order.shipments, nextSortState, shipmentSortValue));
      }
      return;
    }

    const shipmentNo = event.target.closest("[data-shipment-detail]")?.dataset.shipmentDetail;
    if (shipmentNo) window.location.hash = buildRouteWithReturn(`/shipments/${encodeURIComponent(shipmentNo)}`, getCurrentLocation());
  });

  page?.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    if (contractLayer && !contractLayer.hidden) closeContractDialog();
    else if (reopenLayer && !reopenLayer.hidden) closeReopenDialog();
    else if (completeLayer && !completeLayer.hidden) closeCompleteDialog();
    else if (publishLayer && !publishLayer.hidden) closePublishDialog();
  });
}
