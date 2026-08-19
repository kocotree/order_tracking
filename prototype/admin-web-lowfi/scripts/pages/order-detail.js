import { orderDetailData, orderListData } from "../mock-data.js";
import { escapeHTML, showToast } from "../components/app-shell.js";
import { getNextSortState, renderSortableHeader, sortRows, updateSortHeaders } from "../components/table-sort.js";

const backIcon = `<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="m15 18-6-6 6-6" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>`;
const productIcon = `<svg viewBox="0 0 28 34" fill="none" aria-hidden="true"><path d="m9 5 5-2 5 2 5 6-4 3v15H8V14l-4-3 5-6Z" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"/><path d="M11 5c.6 2 1.6 3 3 3s2.4-1 3-3" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/></svg>`;

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
          <td class="detail-sequence">${index + 1}</td>
          <td>
            <span class="product-thumb" aria-label="产品图片未上传">${productIcon}</span>
          </td>
          <td class="detail-code">${escapeHTML(product.code)}</td>
          <td><strong class="detail-product-name">${escapeHTML(product.name)}</strong></td>
          <td>${escapeHTML(product.colorSpec)}</td>
          <td>${escapeHTML(product.factory)}</td>
          <td class="detail-number">${escapeHTML(formatNumber(product.quantity))}</td>
          <td class="detail-number">${escapeHTML(formatNumber(product.shippedQuantity))}</td>
          <td class="detail-number">${escapeHTML(formatNumber(product.pendingQuantity))}</td>
          <td>
            <div class="detail-shipping-progress">
              <span class="progress-track" aria-label="发货进度 ${escapeHTML(product.quantity ? Math.round((product.shippedQuantity / product.quantity) * 100) : 0)}%">
                <span class="progress-bar" style="width: ${escapeHTML(product.quantity ? Math.round((product.shippedQuantity / product.quantity) * 100) : 0)}%"></span>
              </span>
              <span>${escapeHTML(product.quantity ? Math.round((product.shippedQuantity / product.quantity) * 100) : 0)}%</span>
            </div>
          </td>
        </tr>
      `,
    )
    .join("");
}

function renderShipmentRows(shipments) {
  if (shipments.length === 0) {
    return `<tr><td colspan="6"><div class="detail-empty-row">当前订单暂无关联发货单</div></td></tr>`;
  }

  return shipments
    .map(
      (shipment, index) => `
        <tr>
          <td class="detail-sequence">${index + 1}</td>
          <td><button class="row-link" type="button" data-shipment-detail="${escapeHTML(shipment.no)}">${escapeHTML(shipment.no)}</button></td>
          <td>${escapeHTML(shipment.factory)}</td>
          <td>${escapeHTML(shipment.shipDate)}</td>
          <td class="detail-number">${escapeHTML(formatNumber(shipment.declared))}</td>
          <td><span class="status-badge is-${escapeHTML(shipment.tone)}">${escapeHTML(shipment.statusLabel)}</span></td>
        </tr>
      `,
    )
    .join("");
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
    <div class="detail-confirm-layer" hidden data-publish-confirm-layer>
      <button class="detail-confirm-backdrop" type="button" aria-label="取消发布订单" data-publish-confirm-cancel></button>
      <section class="detail-confirm-dialog" role="dialog" aria-modal="true" aria-labelledby="publish-confirm-title" aria-describedby="publish-confirm-description">
        <h2 id="publish-confirm-title">确认发布订单</h2>
        <p id="publish-confirm-description">确认发布订单 <strong>${escapeHTML(order.orderNo)}</strong>？发布后相关工厂将在小程序收到任务，订单状态将变为未完成。</p>
        <div class="detail-confirm-actions">
          <button class="detail-outline-button" type="button" data-publish-confirm-cancel>取消</button>
          <button class="detail-primary-button" type="button" data-publish-confirm-submit>确认发布</button>
        </div>
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
    <section class="detail-confirm-dialog contract-export-dialog" role="dialog" aria-modal="true" aria-labelledby="contract-export-title">
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
        ${factory.contractReady ? "" : `<p class="contract-export-warning">该工厂的合同资料不完整，暂不能导出。请先在工厂资料中补全工厂代码、单位全称、单位地址和法定代表人。</p>`}
      </div>
      <div class="detail-confirm-actions contract-export-actions">
        <button class="detail-outline-button" type="button" data-contract-export-close>取消</button>
        <button class="detail-primary-button" type="button" data-contract-export-submit="${escapeHTML(factory.name)}" ${factory.contractReady ? "" : "disabled"}>确认导出</button>
      </div>
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
        <td>${exported ? escapeHTML(factory.contractNo) : "—"}</td>
        <td>${exported ? escapeHTML(getContractSigningDate(factory)) : "—"}</td>
        <td><button class="detail-text-button" type="button" data-contract-select-factory="${escapeHTML(factory.name)}" ${factory.contractReady ? "" : "disabled"}>导出</button></td>
      </tr>
    `;
  }).join("");

  return `
    <section class="detail-confirm-dialog contract-export-dialog is-factory-list" role="dialog" aria-modal="true" aria-labelledby="contract-export-title">
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
  const order = getOrderDetail(orderNo);
  const productFactoryRows = buildProductFactoryRows(order);
  const isDraft = order.statusKey === "draft";
  const canExportContract = order.factories.length > 0 && Number(order.shippedQuantity) === 0;

  return `
    <article class="order-detail-page" data-order-detail-page data-order-no="${escapeHTML(order.orderNo)}">
      <section class="section-card detail-overview-card">
        <header class="detail-page-header">
          <button class="detail-back-button" type="button" data-order-back>${backIcon}<span>返回</span></button>
          <div class="detail-title-row order-detail-actions">
            <span class="status-badge is-${escapeHTML(order.tone)}">${escapeHTML(order.statusLabel)}</span>
            <button class="detail-outline-button" type="button" data-contract-export-open ${canExportContract ? "" : "disabled"} title="${canExportContract ? "导出加工合同" : "只有已发数量为0的订单才能导出加工合同"}">导出加工合同</button>
            ${isDraft ? `<button class="detail-primary-button" type="button" data-publish-confirm-open>发布订单</button>` : ""}
          </div>
        </header>

        <div class="detail-overview-content">
          <dl class="detail-summary-grid" aria-label="订单概览">
            <div><dt>分类</dt><dd><span class="category-tag is-${order.category === "帽子" ? "hat" : "clothing"}">${escapeHTML(order.category)}</span></dd></div>
            <div><dt>跟单人员</dt><dd><span class="tracker-tag" data-tracker="${escapeHTML(order.tracker)}">${escapeHTML(order.tracker)}</span></dd></div>
            <div><dt>合同出货时间</dt><dd class="detail-due-date">${escapeHTML(order.nearestDue)}</dd></div>
            <div><dt>订单数量</dt><dd class="detail-summary-number">${escapeHTML(formatNumber(order.totalQuantity))}</dd></div>
            <div><dt>已出数量</dt><dd class="detail-summary-number">${escapeHTML(formatNumber(order.shippedQuantity))}</dd></div>
            <div><dt>未出数量</dt><dd class="detail-summary-number">${escapeHTML(formatNumber(order.pendingQuantity))}</dd></div>
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
                <th scope="col">序号</th>
                <th scope="col">图片</th>
                ${renderSortableHeader("产品编码", "code")}
                ${renderSortableHeader("产品名称", "name")}
                ${renderSortableHeader("颜色/规格", "colorSpec")}
                ${renderSortableHeader("工厂", "factory")}
                ${renderSortableHeader("下单数量", "quantity")}
                ${renderSortableHeader("已出数量", "shippedQuantity")}
                ${renderSortableHeader("未出数量", "pendingQuantity")}
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
          <table class="detail-data-table shipment-detail-table data-grid-table" data-sort-table="order-shipments">
            <thead>
              <tr>
                <th scope="col">序号</th>
                ${renderSortableHeader("发货单号", "no")}
                ${renderSortableHeader("工厂", "factory")}
                ${renderSortableHeader("发货日期", "shipDate")}
                ${renderSortableHeader("发货数量", "declared")}
                ${renderSortableHeader("状态", "statusLabel")}
              </tr>
            </thead>
            <tbody data-order-shipments-body>${renderShipmentRows(order.shipments)}</tbody>
          </table>
        </div>
      </section>
      ${isDraft ? renderPublishDialog(order) : ""}
      ${renderContractExportLayer(order)}
    </article>
  `;
}

export function bindOrderDetailPage(orderNo) {
  const page = document.querySelector("[data-order-detail-page]");
  const publishLayer = page?.querySelector("[data-publish-confirm-layer]");
  const publishButton = page?.querySelector("[data-publish-confirm-open]");
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

  page?.querySelector("[data-order-back]")?.addEventListener("click", () => {
    window.location.hash = "/orders";
  });

  publishButton?.addEventListener("click", () => {
    if (!publishLayer) return;
    publishLayer.hidden = false;
    document.body.classList.add("has-dialog-open");
    publishLayer.querySelector("[data-publish-confirm-submit]")?.focus();
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
    showToast("订单发布成功", `${orderNo} 已变为未完成，相关工厂将收到任务。`);
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
    if (shipmentNo) window.location.hash = `/shipments/${encodeURIComponent(shipmentNo)}`;
  });

  page?.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    if (contractLayer && !contractLayer.hidden) closeContractDialog();
    else if (publishLayer && !publishLayer.hidden) closePublishDialog();
  });
}
