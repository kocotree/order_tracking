(function registerShipmentListPage() {
  function getShipments(data) {
    return Object.values(data.shipmentDetails).sort((a, b) => b.shipDate.localeCompare(a.shipDate));
  }

  function getVisibleShipments(data, state) {
    const keyword = state.shipmentKeyword.trim().toLowerCase();
    return getShipments(data).filter((shipment) => {
      const productNames = shipment.lines.map((line) => line.productName).join(" ").toLowerCase();
      const orderNos = shipment.orderNos.join(" ").toLowerCase();
      const matchesKeyword = !keyword || orderNos.includes(keyword) || productNames.includes(keyword);
      const matchesFactory = !state.shipmentFactories.length || state.shipmentFactories.includes(shipment.factory);
      const matchesStart = !state.shipmentDateStart || shipment.shipDate >= state.shipmentDateStart;
      const matchesEnd = !state.shipmentDateEnd || shipment.shipDate <= state.shipmentDateEnd;
      return matchesKeyword && matchesFactory && matchesStart && matchesEnd;
    });
  }

  function renderShipmentCard(shipment, index, icons, formatNumber) {
    const productNames = [...new Set(shipment.lines.map((line) => line.productName))];
    const productSummary = productNames.length > 2 ? `${productNames.slice(0, 2).join("、")}等${productNames.length}款` : productNames.join("、");
    return `
      <button class="shipment-record-card" type="button" data-shipment-no="${shipment.no}" style="--card-index:${index}" aria-label="查看发货单 ${shipment.no} 详情">
        <span class="shipment-record-card__heading">
          <span><small>产品名称</small><strong>${productSummary}</strong></span>
          <span class="shipment-record-card__detail">详情${icons.chevron}</span>
        </span>
        <span class="shipment-record-card__meta">
          <span><i>${icons.factory}</i><small>工厂</small><strong>${shipment.factory}</strong></span>
          <span><i>${icons.calendar}</i><small>发货日期</small><strong>${shipment.shipDate}</strong></span>
        </span>
        <span class="shipment-record-card__stats">
          <span><small>发货数量</small><strong>${formatNumber(shipment.totalQuantity)}</strong></span>
          <span><small>总箱数</small><strong>${shipment.boxes.length}</strong></span>
          <span><small>关联订单</small><strong>${shipment.orderNos.join("、")}</strong></span>
        </span>
        <span class="shipment-record-card__number"><small>发货单号</small><strong>${shipment.no}</strong></span>
      </button>
    `;
  }

  function renderFilterSheet(context, factories) {
    const { icons, state } = context;
    if (!state.shipmentFilterOpen) return "";
    return `
      <div class="sheet-layer" data-close-shipment-sheet>
        <section class="filter-sheet" role="dialog" aria-modal="true" aria-labelledby="shipment-filter-title">
          <div class="sheet-handle" aria-hidden="true"></div>
          <header class="filter-sheet__header">
            <div><p>移动筛选</p><h2 id="shipment-filter-title">筛选发货记录</h2></div>
            <button type="button" class="icon-button" data-close-shipment-sheet aria-label="关闭筛选">${icons.close}</button>
          </header>
          <div class="filter-sheet__body">
            <fieldset class="field factory-field">
              <legend>工厂（可多选）</legend>
              <div class="factory-options">
                ${factories
                  .map(
                    (factory) => `
                      <label>
                        <input class="shipment-factory-option" type="checkbox" value="${factory}" ${state.shipmentFactories.includes(factory) ? "checked" : ""} />
                        <span>${factory}</span>
                      </label>
                    `,
                  )
                  .join("")}
              </div>
            </fieldset>
            <fieldset class="field date-field">
              <legend>发货日期范围</legend>
              <div>
                <input id="shipment-date-start" type="date" value="${state.shipmentDateStart}" aria-label="发货开始日期" />
                <span>至</span>
                <input id="shipment-date-end" type="date" value="${state.shipmentDateEnd}" aria-label="发货结束日期" />
              </div>
            </fieldset>
          </div>
          <footer class="filter-sheet__actions">
            <button type="button" class="secondary-button" id="reset-shipment-filter">重置</button>
            <button type="button" class="primary-button" id="apply-shipment-filter">查看结果</button>
          </footer>
        </section>
      </div>
    `;
  }

  function bindEvents(context) {
    const { state, render, navigate, helpers } = context;
    document.querySelector("#shipment-search")?.addEventListener("input", (event) => {
      state.shipmentKeyword = event.target.value;
      render();
      const input = document.querySelector("#shipment-search");
      input?.focus();
      input?.setSelectionRange(state.shipmentKeyword.length, state.shipmentKeyword.length);
    });

    document.querySelector("#open-shipment-filter")?.addEventListener("click", () => {
      state.shipmentFilterOpen = true;
      render();
    });

    document.querySelectorAll("[data-close-shipment-sheet]").forEach((element) => {
      element.addEventListener("click", (event) => {
        if (event.target.closest(".filter-sheet") && !event.target.closest(".icon-button")) return;
        state.shipmentFilterOpen = false;
        render();
      });
    });

    document.querySelector("#reset-shipment-filter")?.addEventListener("click", () => {
      Object.assign(state, { shipmentFactories: [], shipmentDateStart: "", shipmentDateEnd: "" });
      render();
    });

    document.querySelector("#apply-shipment-filter")?.addEventListener("click", () => {
      state.shipmentFactories = [...document.querySelectorAll(".shipment-factory-option:checked")].map((input) => input.value);
      state.shipmentDateStart = document.querySelector("#shipment-date-start").value;
      state.shipmentDateEnd = document.querySelector("#shipment-date-end").value;
      state.shipmentFilterOpen = false;
      render();
    });

    document.querySelector("#clear-shipment-filters")?.addEventListener("click", () => {
      Object.assign(state, {
        shipmentKeyword: "",
        shipmentFactories: [],
        shipmentDateStart: "",
        shipmentDateEnd: "",
      });
      render();
    });

    document.querySelectorAll("[data-shipment-no]").forEach((button) => {
      button.addEventListener("click", () =>
        navigate("shipment-detail", {
          selectedShipmentNo: button.dataset.shipmentNo,
          shipmentBackPage: "shipments",
        }),
      );
    });

    document.querySelector("[data-page-target='orders']")?.addEventListener("click", () => navigate("orders"));
    document.querySelector("[data-page-target='repairs']")?.addEventListener("click", () => navigate("repairs"));
    document.querySelector("[data-page-target='profile']")?.addEventListener("click", () => navigate("profile"));
    document.querySelectorAll("[data-prototype-target]").forEach((button) => {
      button.addEventListener("click", () => helpers.showToast(`${button.dataset.prototypeTarget}页面将在逐项确认后制作`));
    });
  }

  function mount(context) {
    const { app, data, icons, state, helpers } = context;
    const shipments = getShipments(data);
    const factories = [...new Set(shipments.map((shipment) => shipment.factory))];
    const visibleShipments = getVisibleShipments(data, state);
    const activeFilterCount = [
      state.shipmentFactories.length > 0,
      Boolean(state.shipmentDateStart),
      Boolean(state.shipmentDateEnd),
    ].filter(Boolean).length;

    app.innerHTML = `
      <div class="page-shell shipment-list-page">
        <header class="page-header">
          <div class="mini-titlebar">
            <span class="titlebar-spacer" aria-hidden="true"></span>
            <h1>发货</h1>
            <div class="wechat-capsule" aria-hidden="true"><b>•••</b><i></i><span></span></div>
          </div>
          <div class="shipment-segmented" role="tablist" aria-label="发货板块">
            <button type="button" class="is-active" role="tab" aria-selected="true">发货记录</button>
            <button type="button" role="tab" aria-selected="false" data-page-target="repairs">返修进度</button>
          </div>
          <div class="search-row">
            <label class="search-box">
              ${icons.search}
              <input id="shipment-search" type="search" value="${state.shipmentKeyword}" placeholder="订单编号或产品名称" autocomplete="off" />
            </label>
            <button type="button" class="filter-button" id="open-shipment-filter">
              ${icons.filter}<span>筛选</span>${activeFilterCount ? `<b>${activeFilterCount}</b>` : ""}
            </button>
          </div>
        </header>

        <section class="shipment-record-list" aria-label="发货记录列表">
          <div class="result-summary"><span>共 ${visibleShipments.length} 张发货单</span><em>按发货日期倒序</em></div>
          ${
            visibleShipments.length
              ? visibleShipments.map((shipment, index) => renderShipmentCard(shipment, index, icons, helpers.formatNumber)).join("")
              : `<div class="empty-state"><span>${icons.search}</span><h2>没有符合条件的发货记录</h2><p>可以调整搜索词或筛选条件后再试。</p><button id="clear-shipment-filters" type="button">清除筛选</button></div>`
          }
        </section>

        <nav class="tabbar" aria-label="管理员小程序一级导航">
          <button type="button" class="tabbar__item" data-page-target="orders">${icons.orders}<span>订单</span></button>
          <button type="button" class="tabbar__item is-active">${icons.truck}<span>发货</span></button>
          <button type="button" class="tabbar__item" data-page-target="profile">${icons.profile}<span>我的</span></button>
        </nav>
      </div>
      ${renderFilterSheet(context, factories)}
      <div class="prototype-toast" role="status"></div>
    `;

    bindEvents(context);
  }

  window.AdminPrototypePages ??= {};
  window.AdminPrototypePages.shipments = { mount };
})();
