(function registerOrderDetailPage() {
  function getOrderDetail(order, detailOverrides) {
    if (detailOverrides[order.id]) return detailOverrides[order.id];

    const factoryProgress = order.factories.map((name, index) => {
      const allocated =
        index === order.factories.length - 1
          ? order.total - Math.floor(order.total / order.factories.length) * index
          : Math.floor(order.total / order.factories.length);
      const shipped = Math.min(allocated, Math.round(order.shipped / order.factories.length));
      return {
        name,
        allocated,
        shipped,
        products: order.detailProducts ?? [
          {
            productName: order.productName,
            colorCode: order.specs,
            shipped,
            ordered: allocated,
          },
        ],
      };
    });
    const shipments = order.shipped
      ? [
          {
            no: `FH${order.orderDate.replaceAll("-", "").slice(2)}-001`,
            factory: order.factories[0],
            quantity: order.shipped,
            status: "shipped",
            statusLabel: "已发货",
          },
        ]
      : [];

    return {
      pendingCancellationCount: 0,
      factoryProgress,
      shipments,
    };
  }

  function renderFactoryProgress(factory, formatNumber) {
    const shippedPercent = factory.allocated ? Math.round((factory.shipped / factory.allocated) * 100) : 0;
    const unshipped = Math.max(factory.allocated - factory.shipped, 0);
    return `
      <article class="factory-progress-card">
        <div class="factory-progress-card__top"><h3>${factory.name}</h3><strong>${shippedPercent}%</strong></div>
        <div class="factory-progress-card__numbers">
          <span>下单 <b>${formatNumber(factory.allocated)}</b></span>
          <span>已发 <b>${formatNumber(factory.shipped)}</b></span>
          <span>未发 <b>${formatNumber(unshipped)}</b></span>
        </div>
        <div class="progress-track factory-progress-track"><i style="width:${shippedPercent}%"></i></div>
        <div class="factory-product-table">
          <div class="factory-product-table__head">
            <span>产品名称</span><span>颜色规格</span><span>已出/下单</span>
          </div>
          ${factory.products
            .map(
              (product) => `
                <div class="factory-product-row">
                  <strong>${product.productName}</strong>
                  <span>${product.colorCode}</span>
                  <b>${formatNumber(product.shipped)} / ${formatNumber(product.ordered)}</b>
                </div>
              `,
            )
            .join("")}
        </div>
      </article>
    `;
  }

  function renderShipment(shipment, icons, formatNumber) {
    return `
      <button class="shipment-row" type="button" data-shipment-no="${shipment.no}">
        <span class="shipment-row__icon">${icons.box}</span>
        <span class="shipment-row__main"><strong>${shipment.no}</strong><small>${shipment.factory} · ${formatNumber(shipment.quantity)}件</small></span>
        <span class="shipment-status shipment-status--${shipment.status}">${shipment.statusLabel}</span>
        ${icons.chevron}
      </button>
    `;
  }

  function renderCompletionDialog(order, state, icons) {
    if (!state.completionDialogOpen) return "";
    return `
      <div class="confirm-layer" data-close-completion>
        <section class="confirm-dialog" role="alertdialog" aria-modal="true" aria-labelledby="completion-title">
          <span class="confirm-dialog__icon">${icons.check}</span>
          <h2 id="completion-title">确认订单完成？</h2>
          <p>确认后订单 ${order.orderNo} 将不再继续发货，并记录当前多发或少发结果。</p>
          <div>
            <button type="button" class="secondary-button" data-close-completion>取消</button>
            <button type="button" class="primary-button" id="confirm-completion">确认完成</button>
          </div>
        </section>
      </div>
    `;
  }

  function bindEvents(context, order) {
    const { state, render, navigate } = context;
    document.querySelector("#back-to-orders")?.addEventListener("click", () => {
      state.completionDialogOpen = false;
      navigate("orders");
    });

    document.querySelectorAll("[data-shipment-no]").forEach((button) => {
      button.addEventListener("click", () =>
        navigate("shipment-detail", {
          selectedShipmentNo: button.dataset.shipmentNo,
          shipmentBackPage: "order-detail",
        }),
      );
    });

    document.querySelector("#complete-order:not(:disabled)")?.addEventListener("click", () => {
      state.completionDialogOpen = true;
      render();
    });

    document.querySelectorAll("[data-close-completion]").forEach((element) => {
      element.addEventListener("click", (event) => {
        if (event.target.closest(".confirm-dialog") && !event.target.closest("[data-close-completion]")) return;
        state.completionDialogOpen = false;
        render();
      });
    });

    document.querySelector("#confirm-completion")?.addEventListener("click", () => {
      order.status = "completed";
      order.statusLabel = "已完成";
      order.overdueDays = 0;
      state.completionDialogOpen = false;
      render();
    });
  }

  function mount(context) {
    const { app, data, icons, state, helpers } = context;
    const order = data.orders.find((item) => item.id === state.selectedOrderId) ?? data.orders[0];
    const detail = getOrderDetail(order, data.detailOverrides);
    const canComplete =
      !["draft", "cancelled", "completed"].includes(order.status) && detail.pendingCancellationCount === 0;
    const blockedReason = detail.pendingCancellationCount
      ? `仍有 ${detail.pendingCancellationCount} 张待处理作废申请`
      : "全部发货记录核对完成后可确认";

    app.innerHTML = `
      <div class="detail-page">
        <header class="detail-titlebar">
          <button type="button" class="back-button" id="back-to-orders" aria-label="返回订单列表">${icons.back}</button>
          <h1>订单详情</h1>
          <div class="wechat-capsule" aria-hidden="true"><b>•••</b><i></i><span></span></div>
        </header>

        <div class="detail-content">
          <section class="detail-summary-card">
            <div class="order-card__heading">
              <div><p class="order-card__number">${order.orderNo}</p><h2>${order.productName}</h2></div>
              <div class="order-card__badges">
                <span class="status status--${order.status}">${order.statusLabel}</span>
                ${order.overdueDays > 0 ? `<span class="overdue">逾期${order.overdueDays}天</span>` : ""}
              </div>
            </div>

            <div class="summary-facts">
              <p><span class="fact-icon">${icons.user}</span><span>跟单人员</span><strong>${order.tracker}</strong></p>
              <p><span class="fact-icon">${icons.orders}</span><span>订单数量</span><strong>${helpers.formatNumber(order.total)}</strong></p>
            </div>

            <p class="summary-due">
              <span class="fact-icon">${icons.calendar}</span>
              <span>合同出货时间</span>
              <strong>${order.contractShipDate}</strong>
            </p>

            <div class="summary-progress">
              <div>
                <span>发货进度</span><div class="progress-track"><i style="width:${order.progress}%"></i></div><strong>${order.progress}%</strong>
                <small>${helpers.formatNumber(order.shipped)} / ${helpers.formatNumber(order.total)}</small>
              </div>
            </div>
          </section>

          <section class="detail-section">
            <header><h2>工厂进度</h2><span>${detail.factoryProgress.length} 个工厂</span></header>
            <div class="factory-progress-list">
              ${detail.factoryProgress.map((factory) => renderFactoryProgress(factory, helpers.formatNumber)).join("")}
            </div>
          </section>

          <section class="detail-section">
            <header><h2>关联发货单</h2><span>${detail.shipments.length} 张</span></header>
            <div class="shipment-list">
              ${
                detail.shipments.length
                  ? detail.shipments.map((shipment) => renderShipment(shipment, icons, helpers.formatNumber)).join("")
                  : '<p class="detail-empty">暂无关联发货单</p>'
              }
            </div>
          </section>

          <div class="completion-hint ${canComplete ? "is-ready" : ""}">
            ${icons.info}<span>${order.status === "completed" ? "订单已确认完成" : canComplete ? "已满足订单完成检查条件" : blockedReason}</span>
          </div>
        </div>

        <footer class="completion-bar">
          <button type="button" id="complete-order" ${canComplete ? "" : "disabled"}>
            ${order.status === "completed" ? "订单已完成" : "确认订单完成"}
          </button>
        </footer>
      </div>
      ${renderCompletionDialog(order, state, icons)}
      <div class="prototype-toast" role="status"></div>
    `;

    bindEvents(context, order);
  }

  window.AdminPrototypePages ??= {};
  window.AdminPrototypePages["order-detail"] = { mount };
})();
