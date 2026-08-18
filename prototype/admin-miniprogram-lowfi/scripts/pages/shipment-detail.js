(function registerShipmentDetailPage() {
  function renderShipmentLines(lines, formatNumber) {
    return `
      <div class="shipment-line-table">
        <div class="shipment-line-table__head">
          <span>产品名称</span><span>颜色规格</span><span>发货数量</span>
        </div>
        ${lines
          .map(
            (line) => `
              <div class="shipment-line-row">
                <div><strong>${line.productName}</strong></div>
                <span>${line.colorSpec}</span>
                <b>${formatNumber(line.quantity)}</b>
              </div>
            `,
          )
          .join("")}
      </div>
    `;
  }

  function renderBox(box, icons, formatNumber) {
    const subtotal = box.items.reduce((total, item) => total + item.quantity, 0);
    return `
      <article class="shipment-package-card">
        <header>
          <span class="shipment-package-card__icon">${icons.box}</span>
          <div><strong>箱号 ${box.boxNo}</strong><small>${box.items.length} 个产品规格</small></div>
          <b>合计 ${formatNumber(subtotal)}</b>
        </header>
        <div class="shipment-item-table">
          <div class="shipment-item-table__head">
            <span>产品名称</span><span>颜色规格</span><span>装箱数量</span>
          </div>
          ${box.items
            .map(
              (item) => `
                <div class="shipment-item-row">
                  <div><strong>${item.productName}</strong></div>
                  <span>${item.colorSpec}</span>
                  <b>${formatNumber(item.quantity)}</b>
                </div>
              `,
            )
            .join("")}
        </div>
      </article>
    `;
  }

  function renderLogs(logs) {
    return logs
      .map(
        (log) => `
          <li class="shipment-log-item">
            <i aria-hidden="true"></i>
            <div><strong>${log.action}</strong><span>${log.date} · ${log.operator} · ${log.source}</span></div>
          </li>
        `,
      )
      .join("");
  }

  function bindEvents(context) {
    const { state, navigate } = context;
    document.querySelector("#back-from-shipment")?.addEventListener("click", () => {
      navigate(state.shipmentBackPage || "order-detail");
    });
  }

  function mount(context) {
    const { app, data, icons, state, helpers } = context;
    const shipment = data.shipmentDetails[state.selectedShipmentNo] ?? Object.values(data.shipmentDetails)[0];

    app.innerHTML = `
      <div class="shipment-detail-page">
        <header class="detail-titlebar">
          <button type="button" class="back-button" id="back-from-shipment" aria-label="返回">${icons.back}</button>
          <h1>发货单详情</h1>
          <div class="wechat-capsule" aria-hidden="true"><b>•••</b><i></i><span></span></div>
        </header>

        <div class="shipment-detail-content">
          <section class="shipment-summary-card">
            <div class="shipment-summary-card__heading">
              <div><small>发货单号</small><h2>${shipment.no}</h2></div>
            </div>
            <div class="shipment-summary-grid">
              <p><span>工厂</span><strong>${shipment.factory}</strong></p>
              <p><span>发货日期</span><strong>${shipment.shipDate}</strong></p>
              <p><span>发货数量</span><strong>${helpers.formatNumber(shipment.totalQuantity)}</strong></p>
              <p><span>总箱数</span><strong>${shipment.boxes.length}</strong></p>
              <p class="shipment-summary-grid__wide"><span>关联订单</span><strong>${shipment.orderNos.join("、")}</strong></p>
            </div>
          </section>

          <section class="shipment-detail-section">
            <header><h2>发货明细</h2><span>${shipment.lines.length} 个规格</span></header>
            ${renderShipmentLines(shipment.lines, helpers.formatNumber)}
          </section>

          <section class="shipment-detail-section">
            <header><h2>装箱明细</h2><span>${shipment.boxes.length} 箱</span></header>
            <div class="shipment-package-list">
              ${shipment.boxes.map((box) => renderBox(box, icons, helpers.formatNumber)).join("")}
            </div>
          </section>

          <section class="shipment-detail-section">
            <header><h2>发货凭证与工厂备注</h2><span>${shipment.proofs.length} 张凭证</span></header>
            <div class="shipment-materials">
              <div class="shipment-proof-grid">
                ${shipment.proofs
                  .map(
                    (proof, index) => `
                      <div class="shipment-proof" aria-label="${proof}">
                        <span>${icons.box}</span><small>${index + 1}</small><strong>${proof}</strong>
                      </div>
                    `,
                  )
                  .join("")}
              </div>
              <div class="shipment-note"><span>工厂备注</span><p>${shipment.note || "无"}</p></div>
            </div>
          </section>

          <section class="shipment-detail-section">
            <header><h2>操作记录</h2><span>${shipment.logs.length} 条</span></header>
            <ol class="shipment-log-list">${renderLogs(shipment.logs)}</ol>
          </section>
        </div>
      </div>
      <div class="prototype-toast" role="status"></div>
    `;

    bindEvents(context);
  }

  window.AdminPrototypePages ??= {};
  window.AdminPrototypePages["shipment-detail"] = { mount };
})();
