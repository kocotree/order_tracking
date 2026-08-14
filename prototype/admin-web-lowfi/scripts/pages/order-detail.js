import { orderDetailData, orderListData } from "../mock-data.js";
import { escapeHTML, showToast } from "../components/app-shell.js";

const backIcon = `<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="m15 18-6-6 6-6" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>`;
const productIcon = `<svg viewBox="0 0 28 34" fill="none" aria-hidden="true"><path d="m9 5 5-2 5 2 5 6-4 3v15H8V14l-4-3 5-6Z" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"/><path d="M11 5c.6 2 1.6 3 3 3s2.4-1 3-3" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/></svg>`;

function formatNumber(value) {
  return new Intl.NumberFormat("zh-CN").format(Number(value) || 0);
}

function buildFallbackDetail(orderNo) {
  const sourceOrder = orderListData.orders.find((item) => item.orderNo === orderNo) ?? orderListData.orders[0];
  const factories = sourceOrder.factory.split(/[、,，]/).map((value) => value.trim());
  const totalQuantity = Number(sourceOrder.shippedText.split("/")[1]?.replaceAll(",", "").trim()) || 0;
  const shippedQuantity = Number(sourceOrder.shippedText.split("/")[0]?.replaceAll(",", "").trim()) || 0;
  const receivedQuantity = Number(sourceOrder.receivedText.split("/")[0]?.replaceAll(",", "").trim()) || 0;

  return {
    ...sourceOrder,
    orderDate: sourceOrder.orderDate,
    source: "飞书多维表格导入",
    statusLabel: sourceOrder.overdueDays > 0 ? "已逾期" : sourceOrder.statusLabel,
    tone: sourceOrder.overdueDays > 0 ? "danger" : sourceOrder.tone,
    totalQuantity,
    shippedQuantity,
    receivedQuantity,
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
      received: Math.round(receivedQuantity / factories.length),
      statusLabel: sourceOrder.statusLabel,
      tone: sourceOrder.tone,
      contractReady: true,
      lines: [
        {
          colorSpec: sourceOrder.specSummary,
          dueDate: sourceOrder.nearestDue,
          quantity: Math.round(totalQuantity / factories.length),
          price: "",
          shipped: Math.round(shippedQuantity / factories.length),
          received: Math.round(receivedQuantity / factories.length),
        },
      ],
    })),
    shipments: [],
    logs: [{ time: sourceOrder.updatedAt.replace("T", " ").slice(0, 16), operator: sourceOrder.tracker, action: "更新订单信息", source: "管理员网页端" }],
  };
}

function getOrderDetail(orderNo) {
  return orderDetailData[orderNo] ?? buildFallbackDetail(orderNo);
}

function buildProductFactoryRows(order) {
  return order.products.flatMap((product) => {
    const factoryRows = order.factories.flatMap((factory) =>
      factory.lines
        .filter((line) => line.colorSpec === product.colorSpec)
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
    return `<tr><td colspan="7"><div class="detail-empty-row">当前订单暂无关联发货单</div></td></tr>`;
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
          <td class="detail-number">${typeof shipment.received === "number" ? escapeHTML(formatNumber(shipment.received)) : escapeHTML(shipment.received)}</td>
          <td><span class="status-badge is-${escapeHTML(shipment.tone)}">${escapeHTML(shipment.statusLabel)}</span></td>
        </tr>
      `,
    )
    .join("");
}

function renderPublishDialog(order) {
  return `
    <div class="detail-confirm-layer" hidden data-publish-confirm-layer>
      <button class="detail-confirm-backdrop" type="button" aria-label="取消发布订单" data-publish-confirm-cancel></button>
      <section class="detail-confirm-dialog" role="dialog" aria-modal="true" aria-labelledby="publish-confirm-title" aria-describedby="publish-confirm-description">
        <h2 id="publish-confirm-title">确认发布订单</h2>
        <p id="publish-confirm-description">确认发布订单 <strong>${escapeHTML(order.orderNo)}</strong>？发布后相关工厂将在小程序收到任务，订单状态将变为待发货。</p>
        <div class="detail-confirm-actions">
          <button class="detail-outline-button" type="button" data-publish-confirm-cancel>取消</button>
          <button class="detail-primary-button" type="button" data-publish-confirm-submit>确认发布</button>
        </div>
      </section>
    </div>
  `;
}

export function renderOrderDetailPage(orderNo) {
  const order = getOrderDetail(orderNo);
  const productFactoryRows = buildProductFactoryRows(order);
  const isDraft = order.statusKey === "draft";

  return `
    <article class="order-detail-page" data-order-detail-page data-order-no="${escapeHTML(order.orderNo)}">
      <section class="section-card detail-overview-card">
        <header class="detail-page-header">
          <button class="detail-back-button" type="button" data-order-back>${backIcon}<span>返回</span></button>
          <div class="detail-title-row order-detail-actions">
            <span class="status-badge is-${escapeHTML(order.tone)}">${escapeHTML(order.statusLabel)}</span>
            ${isDraft ? `<button class="detail-primary-button" type="button" data-publish-confirm-open>发布订单</button>` : ""}
          </div>
        </header>

        <div class="detail-overview-content">
          <dl class="detail-summary-grid" aria-label="订单概览">
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
        <header class="detail-section-header">
          <h2>订单明细</h2>
        </header>
        <div class="detail-table-scroll">
          <table class="detail-data-table product-detail-table">
            <thead>
              <tr>
                <th scope="col">序号</th>
                <th scope="col">图片</th>
                <th scope="col">产品编码</th>
                <th scope="col">产品名称</th>
                <th scope="col">颜色/规格</th>
                <th scope="col">工厂</th>
                <th scope="col">下单数量</th>
                <th scope="col">已出数量</th>
                <th scope="col">未出数量</th>
                <th scope="col">发货进度</th>
              </tr>
            </thead>
            <tbody>${renderProductRows(productFactoryRows)}</tbody>
          </table>
        </div>
      </section>

      <section class="section-card detail-section-card">
        <header class="detail-section-header">
          <h2>关联发货单</h2>
        </header>
        <div class="detail-table-scroll">
          <table class="detail-data-table shipment-detail-table">
            <thead>
              <tr>
                <th scope="col">序号</th>
                <th scope="col">发货单号</th>
                <th scope="col">工厂</th>
                <th scope="col">发货日期</th>
                <th scope="col">申报数量</th>
                <th scope="col">实际收到</th>
                <th scope="col">状态</th>
              </tr>
            </thead>
            <tbody>${renderShipmentRows(order.shipments)}</tbody>
          </table>
        </div>
      </section>
      ${isDraft ? renderPublishDialog(order) : ""}
    </article>
  `;
}

export function bindOrderDetailPage(orderNo) {
  const page = document.querySelector("[data-order-detail-page]");
  const publishLayer = page?.querySelector("[data-publish-confirm-layer]");
  const publishButton = page?.querySelector("[data-publish-confirm-open]");

  const closePublishDialog = () => {
    if (publishLayer) publishLayer.hidden = true;
    document.body.classList.remove("has-dialog-open");
    publishButton?.focus();
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

  page?.querySelectorAll("[data-publish-confirm-cancel]").forEach((button) => {
    button.addEventListener("click", closePublishDialog);
  });

  page?.querySelector("[data-publish-confirm-submit]")?.addEventListener("click", () => {
    const sourceOrder = orderListData.orders.find((item) => item.orderNo === orderNo);
    if (sourceOrder) {
      sourceOrder.statusKey = "pending";
      sourceOrder.statusLabel = "待发货";
      sourceOrder.tone = "warning";
      sourceOrder.updatedAt = new Date().toISOString();
    }

    const detailOrder = orderDetailData[orderNo];
    if (detailOrder) {
      detailOrder.statusKey = "pending";
      detailOrder.statusLabel = "待发货";
      detailOrder.tone = "warning";
    }

    if (publishLayer) publishLayer.remove();
    document.body.classList.remove("has-dialog-open");
    const statusBadge = page?.querySelector(".order-detail-actions .status-badge");
    if (statusBadge) {
      statusBadge.className = "status-badge is-warning";
      statusBadge.textContent = "待发货";
    }
    publishButton?.remove();
    showToast("订单发布成功", `${orderNo} 已变为待发货，相关工厂将收到任务。`);
  });

  page?.addEventListener("click", (event) => {
    const shipmentNo = event.target.closest("[data-shipment-detail]")?.dataset.shipmentDetail;
    if (shipmentNo) showToast("发货单详情待设计", `${shipmentNo} 将在发货单详情页中展示装箱和收货信息。`);
  });

  page?.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && publishLayer && !publishLayer.hidden) closePublishDialog();
  });
}
