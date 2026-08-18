(function registerShipmentDetailPage() {
  function renderPackageGroup(group, icons, formatNumber) {
    return `
      <article class="shipment-package-card">
        <header>
          <span class="shipment-package-card__icon">${icons.box}</span>
          <div><strong>${group.name}</strong><small>箱号 ${group.boxNos}</small></div>
          <b>${group.boxCount} 箱</b>
        </header>
        <div class="shipment-item-table">
          <div class="shipment-item-table__head">
            <span>产品信息</span><span>颜色规格</span><span>发货数量</span>
          </div>
          ${group.items
            .map(
              (item) => `
                <div class="shipment-item-row">
                  <div><small>${item.orderNo}</small><strong>${item.productName}</strong></div>
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

  function bindEvents(context) {
    const { state, navigate } = context;
    document.querySelector("#back-from-shipment")?.addEventListener("click", () => {
      navigate(state.shipmentBackPage || "order-detail");
    });
  }

  function mount(context) {
    const { app, data, icons, state, helpers } = context;
    const shipment = data.shipmentDetails[state.selectedShipmentNo] ?? Object.values(data.shipmentDetails)[0];
    const boxCount = shipment.packageGroups.reduce((total, group) => total + group.boxCount, 0);

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
              <span class="shipment-detail-status">${shipment.statusLabel}</span>
            </div>
            <div class="shipment-summary-grid">
              <p><span>工厂</span><strong>${shipment.factory}</strong></p>
              <p><span>发货日期</span><strong>${shipment.shipDate}</strong></p>
              <p><span>发货总数量</span><strong>${helpers.formatNumber(shipment.totalQuantity)}</strong></p>
              <p><span>关联订单</span><strong>${shipment.orderNos.join("、")}</strong></p>
            </div>
          </section>

          <section class="shipment-detail-section">
            <header><h2>装箱明细</h2><span>${boxCount} 箱</span></header>
            <div class="shipment-package-list">
              ${shipment.packageGroups.map((group) => renderPackageGroup(group, icons, helpers.formatNumber)).join("")}
            </div>
          </section>

          <section class="shipment-detail-section">
            <header><h2>发货资料</h2><span>${shipment.proofs.length} 张凭证</span></header>
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
              <div class="shipment-note"><span>备注</span><p>${shipment.note || "无"}</p></div>
            </div>
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
