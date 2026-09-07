import { orderDetailData, orderListData, shipmentDetailData, shipmentListData } from "../mock-data.js";
import { escapeHTML, showToast } from "../components/app-shell.js";
import { getNextSortState, renderSortableHeader, sortRows, updateSortHeaders } from "../components/table-sort.js";
import { getReturnRoute } from "../router.js";

const backIcon = `<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="m15 18-6-6 6-6" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>`;
const photoIcon = `<svg viewBox="0 0 40 40" fill="none" aria-hidden="true"><rect x="5" y="7" width="30" height="26" rx="3" stroke="currentColor" stroke-width="1.8"/><circle cx="15" cy="16" r="3" stroke="currentColor" stroke-width="1.8"/><path d="m9 29 8-8 5 5 4-4 5 7" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>`;

function formatNumber(value) {
  return new Intl.NumberFormat("zh-CN").format(Number(value) || 0);
}

function buildFallbackDetail(shipment) {
  const firstQuantity = Math.ceil(shipment.shippedQuantity / 2);
  const secondQuantity = shipment.shippedQuantity - firstQuantity;
  const firstColorSpec = "雾蓝 / 120";
  const secondColorSpec = "岩灰 / 120";
  return {
    totalBoxes: 2,
    lines: [
      { orderNo: shipment.orderNos[0], code: "KQ26001", name: "户外功能上装", colorSpec: firstColorSpec, shippedQuantity: firstQuantity },
      { orderNo: shipment.orderNos.at(-1), code: "KQ26002", name: "户外功能下装", colorSpec: secondColorSpec, shippedQuantity: secondQuantity },
    ],
    boxes: [
      { boxNo: 1, items: [{ orderNo: shipment.orderNos[0], code: "KQ26001", name: "户外功能上装", colorSpec: firstColorSpec, quantity: Math.ceil(firstQuantity / 2) }, { orderNo: shipment.orderNos.at(-1), code: "KQ26002", name: "户外功能下装", colorSpec: secondColorSpec, quantity: Math.ceil(secondQuantity / 2) }] },
      { boxNo: 2, items: [{ orderNo: shipment.orderNos[0], code: "KQ26001", name: "户外功能上装", colorSpec: firstColorSpec, quantity: Math.floor(firstQuantity / 2) }, { orderNo: shipment.orderNos.at(-1), code: "KQ26002", name: "户外功能下装", colorSpec: secondColorSpec, quantity: Math.floor(secondQuantity / 2) }] },
    ],
    proofCount: 0,
    factoryRemark: "—",
    logs: [{ time: `${shipment.shipDate} 10:00`, operator: `${shipment.factory}工厂`, action: "提交发货单，发货记录立即生效", source: "工厂小程序" }],
  };
}

function getShipment(shipmentNo) {
  return shipmentListData.shipments.find((item) => item.shipmentNo === shipmentNo) ?? shipmentListData.shipments[0];
}

function getShipmentDetail(shipment) {
  if (!shipmentDetailData[shipment.shipmentNo]) shipmentDetailData[shipment.shipmentNo] = buildFallbackDetail(shipment);
  const detail = shipmentDetailData[shipment.shipmentNo];
  if (shipment.statusKey === "void-pending" && !detail.voidRequest) detail.voidRequest = { status: "pending", name: "示例工厂用户", time: `${shipment.shipDate} 12:00`, reason: "装箱数量填写有误，申请撤回后重新提交" };
  return detail;
}

function renderShipmentLines(lines) {
  return lines.map((line, index) => `
    <tr>
      <td class="detail-sequence-cell">${index + 1}</td>
      <td>${escapeHTML(line.orderNo)}</td>
      <td class="detail-code">${escapeHTML(line.code)}</td>
      <td><strong class="detail-product-name">${escapeHTML(line.name)}</strong></td>
      <td>${escapeHTML(line.colorSpec)}</td>
      <td class="detail-number">${escapeHTML(formatNumber(line.shippedQuantity))}</td>
    </tr>
  `).join("");
}

function renderPackingGroups(boxes, editable = false) {
  return boxes.map((box, boxIndex) => {
    const subtotal = box.items.reduce((sum, item) => sum + Number(item.quantity || 0), 0);
    return `
      <tbody class="packing-box-group">
        ${box.items.map((item, index) => `
          <tr>
            ${index === 0 ? `<td class="packing-box-number" rowspan="${box.items.length}">${escapeHTML(box.boxNo)}</td>` : ""}
            <td>${escapeHTML(item.orderNo)}</td>
            <td class="detail-code">${escapeHTML(item.code)}</td>
            <td>${escapeHTML(item.name)}</td>
            <td>${escapeHTML(item.colorSpec)}</td>
            <td class="detail-number">${editable ? `<input class="return-quantity-input" type="number" min="0" max="2147483647" step="1" value="${item.quantity}" data-receipt-quantity="${boxIndex}:${index}" aria-label="箱号 ${box.boxNo} ${escapeHTML(item.code)} 核对数量" />` : formatNumber(item.quantity)}</td>
            <td class="packing-total-cell">${index === box.items.length - 1 ? escapeHTML(formatNumber(subtotal)) : ""}</td>
          </tr>
        `).join("")}
      </tbody>
    `;
  }).join("");
}

function shipmentLineSortValue(line, key) {
  return line[key];
}

function packingItemSortValue(item, key) {
  return item[key];
}

function packingSubtotal(box) {
  return box.items.reduce((sum, item) => sum + Number(item.quantity || 0), 0);
}

function sortPackingBoxes(boxes, sortState) {
  if (sortState.key === "boxNo") return sortRows(boxes, sortState, (box) => box.boxNo);
  if (sortState.key === "total") return sortRows(boxes, sortState, packingSubtotal);
  return boxes.map((box) => ({ ...box, items: sortRows(box.items, sortState, packingItemSortValue) }));
}

function renderProofs(count) {
  if (!count) return `<div class="shipment-proof-empty">工厂未上传发货凭证</div>`;
  return `<div class="shipment-proof-list">${Array.from({ length: count }, (_, index) => `<div class="shipment-proof-item">${photoIcon}<span>发货凭证 ${index + 1}</span></div>`).join("")}</div>`;
}

function renderLogs(logs) {
  return logs.map((log) => `
    <li class="shipment-log-item">
      <span class="shipment-log-dot" aria-hidden="true"></span>
      <div><strong>${escapeHTML(log.action)}</strong><span>${escapeHTML(log.time)} · ${escapeHTML(log.operator)} · ${escapeHTML(log.source)}</span></div>
    </li>
  `).join("");
}

function getAvailableReturnQuantity(line) {
  return Math.max(Number(line.shippedQuantity || 0) - Number(line.returnedQuantity || 0), 0);
}

function renderReturnDialog(shipment, detail) {
  const rows = detail.lines.map((line, index) => {
    const availableQuantity = getAvailableReturnQuantity(line);
    return `
      <tr>
        <td><input type="checkbox" aria-label="选择 ${escapeHTML(line.name)} ${escapeHTML(line.colorSpec)}" data-return-line-check="${index}" ${availableQuantity === 0 ? "disabled" : ""} /></td>
        <td>${escapeHTML(line.orderNo)}</td>
        <td class="detail-code">${escapeHTML(line.code)}</td>
        <td>${escapeHTML(line.name)}</td>
        <td>${escapeHTML(line.colorSpec)}</td>
        <td class="detail-number">${escapeHTML(formatNumber(line.shippedQuantity))}</td>
        <td class="detail-number">${escapeHTML(formatNumber(availableQuantity))}</td>
        <td><input class="return-quantity-input" type="number" min="1" max="${escapeHTML(availableQuantity)}" inputmode="numeric" disabled data-return-line-quantity="${index}" /></td>
      </tr>
    `;
  }).join("");
  return `
    <div class="detail-confirm-layer" hidden data-return-layer>
      <button class="detail-confirm-backdrop" type="button" aria-label="取消退回商品" data-return-cancel></button>
      <section class="modal shipment-return-dialog" role="dialog" aria-modal="true" aria-labelledby="return-title">
        <header >
          <h2 id="return-title">按发货单退回</h2>
          <button type="button" aria-label="关闭" data-return-cancel>×</button>
        </header>
        <div class="modal-body"><div class="detail-table-scroll">
          <table class="shipment-return-table data-grid-table">
            <thead><tr><th scope="col">选择</th><th scope="col">订单编号</th><th scope="col">产品编码</th><th scope="col">产品名称</th><th scope="col">颜色/规格</th><th scope="col">发货数量</th><th scope="col">可退数量</th><th scope="col">本次退回数量</th></tr></thead>
            <tbody>${rows}</tbody>
          </table>
        </div>
        <label class="return-reason-field"><span>退回原因</span><textarea rows="3" maxlength="500" placeholder="请填写本次选中产品共用的退回原因" data-return-reason></textarea></label>
        </div><footer>
          <button class="detail-outline-button" type="button" data-return-cancel>取消</button>
          <button class="detail-primary-button" type="button" data-return-submit>确认退回</button>
        </footer>
      </section>
    </div>
  `;
}

function updateOrderAfterReturn(shipment, returnedLines, reason, time, operation = "退回") {
  const orderTotals = new Map();
  returnedLines.filter(item => item.quantity !== 0).forEach(({ line, quantity }) => {
    orderTotals.set(line.orderNo, (orderTotals.get(line.orderNo) || 0) + quantity);
    const order = orderDetailData[line.orderNo];
    if (!order) return;
    const product = order.products.find((item) => item.code === line.code && item.colorSpec === line.colorSpec);
    if (product) {
      product.shippedQuantity = Math.max(Number(product.shippedQuantity || 0) - quantity, 0);
      product.pendingQuantity = Math.max(Number(product.quantity || 0) - product.shippedQuantity, 0);
    }
    const factory = order.factories.find((item) => item.name === shipment.factory);
    const factoryLine = factory?.lines.find((item) => (!item.code || item.code === line.code) && item.colorSpec === line.colorSpec);
    if (factoryLine) factoryLine.shipped = Math.max(Number(factoryLine.shipped || 0) - quantity, 0);
  });

  orderTotals.forEach((quantity, orderNo) => {
    const order = orderDetailData[orderNo];
    if (!order) return;
    const listOrder = orderListData.orders.find((item) => item.orderNo === orderNo);
    const isOverdue = Number(listOrder?.overdueDays || 0) > 0;
    const restoredLabel = isOverdue ? "已逾期" : "未完成";
    const restoredTone = isOverdue ? "danger" : "info";
    const shippedBefore = Number(order.shippedQuantity || 0);
    order.shippedQuantity = Math.max(shippedBefore - quantity, 0);
    order.pendingQuantity = Math.max(Number(order.totalQuantity || 0) - order.shippedQuantity, 0);
    order.statusKey = "shipping";
    order.statusLabel = restoredLabel;
    order.tone = restoredTone;
    const factory = order.factories.find((item) => item.name === shipment.factory);
    if (factory) {
      factory.shipped = Math.max(Number(factory.shipped || 0) - quantity, 0);
      factory.statusLabel = restoredLabel;
      factory.tone = restoredTone;
    }
    order.logs.unshift({
      time,
      operator: "煎饼",
      action: `发货单 ${shipment.shipmentNo} ${operation} ${formatNumber(Math.abs(quantity))} 件；已发 ${formatNumber(shippedBefore)}→${formatNumber(order.shippedQuantity)}；原因：${reason}`,
      source: "管理员网页端",
    });

    if (listOrder) {
      listOrder.shippedPercent = order.totalQuantity ? Math.round((order.shippedQuantity / order.totalQuantity) * 100) : 0;
      listOrder.shippedText = `${formatNumber(order.shippedQuantity)} / ${formatNumber(order.totalQuantity)}`;
      listOrder.statusKey = "shipping";
      listOrder.statusLabel = restoredLabel;
      listOrder.tone = restoredTone;
      listOrder.updatedAt = new Date().toISOString();
    }
  });
}

function canVerify(shipment, detail) {
  return shipment.statusKey === "shipped" && !detail.receipt && !detail.returnRecords?.length;
}
function receiptBoxes(detail) {
  return detail.receiptDraft || detail.boxes;
}
function receiptLines(detail, boxes) {
  return detail.lines.map(line => ({ ...line, shippedQuantity: boxes.flatMap(box => box.items).filter(item => item.orderNo === line.orderNo && item.code === line.code && item.colorSpec === line.colorSpec).reduce((sum,item) => sum + Number(item.quantity || 0), 0) }));
}
function renderVoidRequest(shipment, detail) {
  const request = detail.voidRequest;
  if (!request) return "";
  const pending = request.status === "pending";
  return `<section class="section-card shipment-void-card"><header class="detail-section-header"><h2>撤回申请</h2><span class="status-badge is-${pending ? "warning" : request.status === "approved" ? "success" : "danger"}">${{ pending: "待审核", approved: "已通过", rejected: "已拒绝" }[request.status]}</span></header><div class="shipment-void-content"><dl><div><dt>申请人</dt><dd>${escapeHTML(request.name)}</dd></div><div><dt>申请时间</dt><dd>${escapeHTML(request.time)}</dd></div><div class="is-wide"><dt>撤回原因</dt><dd>${escapeHTML(request.reason)}</dd></div>${request.reviewedAt ? `<div><dt>审核时间</dt><dd>${escapeHTML(request.reviewedAt)}</dd></div>` : ""}${request.comment ? `<div class="is-wide"><dt>审核意见</dt><dd>${escapeHTML(request.comment)}</dd></div>` : ""}</dl>${pending ? `<div class="shipment-void-actions"><button class="detail-outline-button" type="button" data-void-review="reject">拒绝</button><button class="detail-primary-button" type="button" data-void-review="approve" ${detail.returnRecords?.length ? 'disabled title="该发货单已有退回记录，只能拒绝"' : ""}>通过</button></div>` : ""}</div></section><div data-void-modal></div>`;
}

export function renderShipmentDetailPage(shipmentNo) {
  if (!(shipmentListData.shipments.some(item => item.shipmentNo === shipmentNo))) return `<article class="section-card notification-target-error"><button class="detail-back-button" type="button" data-route="/shipments">‹ 返回</button><p class="page-error">内容已不可查看</p></article>`;
  const shipment = getShipment(shipmentNo);
  const detail = getShipmentDetail(shipment);
  const isEffective = shipment.statusKey === "shipped";
  const editable = canVerify(shipment, detail);
  const boxes = editable ? receiptBoxes(detail) : detail.boxes;
  const lines = editable ? receiptLines(detail, boxes) : detail.lines;
  const displayTotal = lines.reduce((sum, line) => sum + line.shippedQuantity, 0);
  const shipmentTime = detail.logs.find((item) => item.action.includes("提交发货单"))?.time ?? shipment.shipDate;
  return `
    <article class="order-detail-page shipment-detail-page" data-shipment-detail-page data-shipment-no="${escapeHTML(shipment.shipmentNo)}">
      <section class="section-card detail-overview-card">
        <header class="detail-page-header">
          <button class="detail-back-button" type="button" data-shipment-back>${backIcon}<span>返回</span></button>
          <div class="detail-title-row shipment-detail-actions">
            ${editable ? '<button class="detail-primary-button" type="button" data-confirm-receipt>确认收货</button>' : `<span class="status-badge is-${escapeHTML(shipment.tone)}">${detail.receipt && shipment.statusKey === "shipped" ? "已收货" : escapeHTML(shipment.statusLabel)}</span>`}
            ${detail.receipt ? `<span class="receipt-confirmation">已收货 · ${escapeHTML(detail.receipt.name)} · ${escapeHTML(detail.receipt.time)}</span>` : ""}
            ${shipment.statusKey !== "voided" ? '<button class="detail-outline-button" type="button" data-download-shipment>下载发货清单</button>' : ""}
          </div>
        </header>
        <div class="detail-overview-content">
          <dl class="shipment-summary-grid" aria-label="发货单概览">
            <div><dt>关联订单</dt><dd>${shipment.orderNos.map((orderNo) => escapeHTML(orderNo)).join("、")}</dd></div>
            <div><dt>发货时间</dt><dd>${escapeHTML(shipmentTime)}</dd></div>
            <div><dt>发货数量</dt><dd class="detail-summary-number">${formatNumber(displayTotal)}</dd></div>
            <div><dt>总箱数</dt><dd class="detail-summary-number">${escapeHTML(formatNumber(detail.totalBoxes))}</dd></div>
          </dl>
        </div>
      </section>

      <p class="page-error" hidden data-receipt-error></p><p class="page-state" hidden data-receipt-message></p>
      ${renderVoidRequest(shipment, detail)}
      <section class="section-card detail-section-card">
        <header class="detail-section-header"><h2>发货明细</h2>${isEffective && detail.lines.some(line => getAvailableReturnQuantity(line) > 0) ? `<button class="detail-outline-button" type="button" data-return-open>退回</button>` : ""}</header>
        <div class="detail-table-scroll">
          <table class="detail-data-table shipment-product-table data-grid-table" data-sort-table="shipment-lines"><colgroup><col class="detail-sequence-col" /><col class="detail-order-col" /><col class="detail-sku-col" /><col class="detail-product-col" /><col class="detail-properties-col" /><col class="detail-quantity-col" /></colgroup>
            <thead><tr><th class="detail-sequence-column" scope="col">序号</th>${renderSortableHeader("关联订单", "orderNo")}${renderSortableHeader("产品编码", "code")}${renderSortableHeader("产品名称", "name")}${renderSortableHeader("颜色/规格", "colorSpec")}${renderSortableHeader("发货数量", "shippedQuantity")}</tr></thead>
            <tbody data-shipment-lines-body>${renderShipmentLines(lines)}</tbody>
          </table>
        </div>
      </section>

      <section class="section-card detail-section-card">
        <header class="detail-section-header"><h2>装箱明细</h2>${editable ? `<button class="detail-outline-button" type="button" data-save-receipt>保存</button>` : ""}</header>
        <div class="detail-table-scroll">
          <table class="detail-data-table packing-detail-table data-grid-table" data-sort-table="packing-lines">
            <thead><tr><th>箱号</th><th>关联订单</th><th>产品编码</th><th>产品名称</th><th>颜色/规格</th><th>装箱数量</th><th>合计</th></tr></thead>
            ${renderPackingGroups(boxes, editable)}
          </table>
        </div>
      </section>

      <section class="shipment-support-grid">
        <section class="section-card detail-section-card">
          <header class="detail-section-header"><h2>发货凭证与工厂备注</h2></header>
          <div class="shipment-support-content">
            <div><h3>发货凭证（${escapeHTML(detail.proofCount)} 张）</h3>${renderProofs(detail.proofCount)}</div>
            <div><h3>工厂备注</h3><p class="shipment-factory-remark">${escapeHTML(detail.factoryRemark)}</p></div>
          </div>
        </section>
        <section class="section-card detail-section-card">
          <header class="detail-section-header"><h2>操作记录</h2></header>
          <ol class="shipment-log-list">${renderLogs(detail.logs)}</ol>
        </section>
      </section>
      ${isEffective ? renderReturnDialog(shipment, detail) : ""}
    </article>
  `;
}

export function bindShipmentDetailPage(shipmentNo) {
  const page = document.querySelector("[data-shipment-detail-page]");
  if (!page) return;
  const returnLayer = page?.querySelector("[data-return-layer]");
  const returnOpenButton = page?.querySelector("[data-return-open]");
  const shipment = getShipment(shipmentNo);
  const detail = getShipmentDetail(shipment);
  const draft = structuredClone(receiptBoxes(detail));
  const refresh = () => { document.body.classList.remove("has-dialog-open"); page.outerHTML = renderShipmentDetailPage(shipmentNo); bindShipmentDetailPage(shipmentNo); };
  const feedback = (text, isError = false) => { const error = page.querySelector("[data-receipt-error]"); const message = page.querySelector("[data-receipt-message]"); error.hidden = !isError; message.hidden = isError; (isError ? error : message).textContent = text; };
  page?.addEventListener("input", event => {
    if (!event.target.matches("[data-receipt-quantity]")) return;
    const [boxIndex, itemIndex] = event.target.dataset.receiptQuantity.split(":").map(Number);
    draft[boxIndex].items[itemIndex].quantity = event.target.value === "" ? "" : Number(event.target.value);
    const lines = receiptLines(detail, draft);
    page.querySelector("[data-shipment-lines-body]").innerHTML = renderShipmentLines(lines);
    page.querySelectorAll(".shipment-summary-grid .detail-summary-number")[0].textContent = formatNumber(lines.reduce((sum,line) => sum + line.shippedQuantity, 0));
    const group = event.target.closest("tbody");
    group.querySelector("tr:last-child .packing-total-cell").textContent = formatNumber(draft[boxIndex].items.reduce((sum,item) => sum + Number(item.quantity || 0), 0));
  });
  page?.querySelector("[data-save-receipt]")?.addEventListener("click", () => {
    if (draft.some(box => box.items.some(item => !Number.isInteger(item.quantity) || item.quantity < 0 || item.quantity > 2147483647))) { feedback("核对数量必须为非负整数", true); return; }
    detail.receiptDraft = structuredClone(draft);
    feedback("核对草稿已保存，确认收货后生效");
  });
  page?.querySelector("[data-confirm-receipt]")?.addEventListener("click", () => {
    if (JSON.stringify(draft) !== JSON.stringify(receiptBoxes(detail))) { feedback("有未保存的核对数量，请先保存再确认收货", true); return; }
    const newLines = receiptLines(detail, draft);
    detail.originalBoxes ??= structuredClone(detail.boxes);
    detail.originalLines ??= structuredClone(detail.lines);
    const time = new Date().toLocaleString("zh-CN", { timeZone: "Asia/Shanghai", hour12: false });
    // Reuse the existing quantity rollback path for net shortages; over-receipt must not reopen a completed order.
    const deltas = newLines.map((line,index) => ({ line: detail.lines[index], quantity: detail.lines[index].shippedQuantity - line.shippedQuantity }));
    const completed = new Set(deltas.map(item => item.line.orderNo).filter(no => orderDetailData[no]?.statusKey === "completed"));
    updateOrderAfterReturn(shipment, deltas, "收货核对差额", time, "收货核对调整");
    for (const no of completed) {
      if (deltas.filter(item => item.line.orderNo === no).reduce((sum,item) => sum + item.quantity, 0) <= 0) {
        const order = orderDetailData[no]; Object.assign(order, { statusKey: "completed", statusLabel: "已完成", tone: "success" });
        const item = orderListData.orders.find(item => item.orderNo === no); if (item) Object.assign(item, { statusKey: "completed", statusLabel: "已完成", tone: "success" });
      }
    }
    detail.boxes = structuredClone(draft); detail.lines = newLines; detail.receipt = { name: "煎饼", time }; delete detail.receiptDraft;
    shipment.shippedQuantity = newLines.reduce((sum,line) => sum + line.shippedQuantity, 0);
    refresh();
  });
  let reviewMode = "";
  page?.addEventListener("click", event => {
    const choice = event.target.closest("[data-void-review]");
    if (choice && !choice.disabled) {
      reviewMode = choice.dataset.voidReview;
      page.querySelector("[data-void-modal]").innerHTML = `<div class="modal-backdrop"><section class="modal action-modal" role="dialog" aria-modal="true"><header><h2>${reviewMode === "approve" ? "确认通过撤回申请" : "拒绝撤回申请"}</h2><button type="button" data-void-cancel>×</button></header><div class="modal-body">${reviewMode === "approve" ? `<p>审核通过后将作废整张发货单，并回退发货数量 ${formatNumber(shipment.shippedQuantity)}。</p>` : '<label class="reopen-field">审核意见<textarea maxlength="500" data-void-reason placeholder="请填写拒绝原因"></textarea></label>'}<p class="page-error" hidden data-void-error>请填写拒绝原因</p></div><footer><button class="detail-outline-button" type="button" data-void-cancel>取消</button><button class="detail-primary-button" type="button" data-void-confirm>确认</button></footer></section></div>`;
    }
    if (event.target.closest("[data-void-cancel]")) page.querySelector("[data-void-modal]").innerHTML = "";
    if (event.target.closest("[data-void-confirm]")) {
      const comment = page.querySelector("[data-void-reason]")?.value.trim() || "";
      if (reviewMode === "reject" && !comment) { page.querySelector("[data-void-error]").hidden = false; return; }
      if (reviewMode === "approve" && detail.returnRecords?.length) return;
      detail.voidRequest.status = reviewMode === "approve" ? "approved" : "rejected";
      detail.voidRequest.comment = comment; detail.voidRequest.reviewedAt = new Date().toLocaleString("zh-CN");
      if (reviewMode === "approve") updateOrderAfterReturn(shipment, detail.lines.map(line => ({ line, quantity: line.shippedQuantity })), "撤回发货", detail.voidRequest.reviewedAt, "作废");
      Object.assign(shipment, reviewMode === "approve" ? { statusKey: "voided", statusLabel: "已作废", tone: "danger" } : { statusKey: "shipped", statusLabel: "已发货", tone: "success" });
      refresh();
    }
  });
  const sortStates = {
    "shipment-lines": { key: null, direction: "asc" },
    "packing-lines": { key: null, direction: "asc" },
  };

  const closeReturnDialog = () => {
    if (returnLayer) returnLayer.hidden = true;
    document.body.classList.remove("has-dialog-open");
    returnOpenButton?.focus();
  };

  page?.querySelector("[data-shipment-back]")?.addEventListener("click", () => { window.location.hash = getReturnRoute("/shipments"); });
  page?.querySelector("[data-download-shipment]")?.addEventListener("click", () => showToast("下载发货清单", `${shipmentNo} 的 Excel 发货清单将在正式开发阶段生成。`));
  returnOpenButton?.addEventListener("click", () => {
    if (!returnLayer) return;
    returnLayer.hidden = false;
    document.body.classList.add("has-dialog-open");
    returnLayer.querySelector("[data-return-line-check]:not(:disabled)")?.focus();
  });
  page?.querySelectorAll("[data-return-cancel]").forEach((button) => button.addEventListener("click", closeReturnDialog));
  page?.querySelectorAll("[data-return-line-check]").forEach((checkbox) => checkbox.addEventListener("change", () => {
    const input = page.querySelector(`[data-return-line-quantity="${checkbox.dataset.returnLineCheck}"]`);
    if (!input) return;
    input.disabled = !checkbox.checked;
    input.value = checkbox.checked ? "1" : "";
    if (checkbox.checked) input.focus();
  }));
  page?.addEventListener("click", (event) => {
    const sortTable = event.target.closest("[data-sort-key]")?.closest("[data-sort-table]");
    const sortScope = sortTable?.dataset.sortTable;
    if (!sortScope || !sortStates[sortScope]) return;
    const nextSortState = getNextSortState(event, sortStates[sortScope]);
    sortStates[sortScope] = nextSortState;
    updateSortHeaders(sortTable, nextSortState);
    if (sortScope === "shipment-lines") {
      const body = page.querySelector("[data-shipment-lines-body]");
      if (body) body.innerHTML = renderShipmentLines(sortRows(canVerify(shipment, detail) ? receiptLines(detail, draft) : detail.lines, nextSortState, shipmentLineSortValue));
      return;
    }
    sortTable.querySelectorAll("tbody.packing-box-group").forEach((group) => group.remove());
    sortTable.insertAdjacentHTML("beforeend", renderPackingGroups(sortPackingBoxes(detail.boxes, nextSortState)));
  });
  page?.querySelector("[data-return-submit]")?.addEventListener("click", () => {
    const selected = [...page.querySelectorAll("[data-return-line-check]:checked")].map((checkbox) => {
      const index = Number(checkbox.dataset.returnLineCheck);
      const line = detail.lines[index];
      const input = page.querySelector(`[data-return-line-quantity="${index}"]`);
      return { line, quantity: Number(input?.value), availableQuantity: getAvailableReturnQuantity(line) };
    });
    if (!selected.length) {
      showToast("请选择退回商品", "至少选择一个产品规格并填写退回数量。 ");
      return;
    }
    const invalid = selected.find(({ quantity, availableQuantity }) => !Number.isInteger(quantity) || quantity < 1 || quantity > availableQuantity);
    if (invalid) {
      showToast("退回数量不正确", `本次退回数量必须为 1 到 ${formatNumber(invalid.availableQuantity)} 之间的整数。`);
      return;
    }
    const reason = page.querySelector("[data-return-reason]")?.value.trim();
    if (!reason) {
      showToast("请填写退回原因", "确认退回前需要填写本次退回原因。 ");
      page.querySelector("[data-return-reason]")?.focus();
      return;
    }
    const total = selected.reduce((sum, item) => sum + item.quantity, 0);
    const returnedSummary = selected.map(({ line, quantity }) => `${line.code} ${line.colorSpec} ${formatNumber(quantity)} 件`).join("；");
    const time = new Date().toLocaleString("sv-SE", { timeZone: "Asia/Shanghai", hour12: false }).slice(0, 16);
    selected.forEach(({ line, quantity }) => { line.returnedQuantity = Number(line.returnedQuantity || 0) + quantity; });
    detail.returnRecords ??= [];
    detail.returnRecords.unshift({ time, reason, total, lines: selected.map(({ line, quantity }) => ({ code: line.code, colorSpec: line.colorSpec, quantity })) });
    detail.logs.unshift({ time, operator: "煎饼", action: `退回商品 ${formatNumber(total)} 件：${returnedSummary}；原因：${reason}`, source: "管理员网页端" });
    updateOrderAfterReturn(shipment, selected, reason, time);
    document.body.classList.remove("has-dialog-open");
    page.outerHTML = renderShipmentDetailPage(shipmentNo);
    bindShipmentDetailPage(shipmentNo);
    showToast("退回成功", `已退回 ${formatNumber(total)} 件，工厂可按原订单任务重新补发。`);
  });

  page?.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && returnLayer && !returnLayer.hidden) closeReturnDialog();
  });
}
