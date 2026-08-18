(function registerRepairListPage() {
  function getVisibleRepairs(data, state) {
    const keyword = state.repairKeyword.trim().toLowerCase();
    return [...data.repairRecords]
      .filter((repair) => {
        if (repair.archived === true) return false;
        const matchesKeyword = !keyword || repair.factory.toLowerCase().includes(keyword);
        const matchesFactory = !state.repairFactories.length || state.repairFactories.includes(repair.factory);
        const matchesStart = !state.repairDateStart || repair.returnDate >= state.repairDateStart;
        const matchesEnd = !state.repairDateEnd || repair.returnDate <= state.repairDateEnd;
        return matchesKeyword && matchesFactory && matchesStart && matchesEnd;
      })
      .sort((a, b) => b.returnDate.localeCompare(a.returnDate));
  }

  function getProductSummary(repair, repairDetails) {
    const productNames = [...new Set((repairDetails[repair.repairNo]?.qualityLines ?? []).map((line) => line.productName))];
    if (!productNames.length) return "暂无产品信息";
    return productNames.length === 1 ? productNames[0] : `${productNames[0]}等${productNames.length}款`;
  }

  function renderRepairCard(repair, index, icons, formatNumber, repairDetails) {
    const returnedQuantity = repair.repairedQuantity + repair.scrappedQuantity;
    const pendingQuantity = Math.max(repair.warehouseReturnQuantity - returnedQuantity, 0);
    const progress = repair.warehouseReturnQuantity
      ? Math.min(100, Math.round((returnedQuantity / repair.warehouseReturnQuantity) * 100))
      : 0;
    const productSummary = getProductSummary(repair, repairDetails);
    return `
      <button class="repair-progress-card" type="button" data-repair-no="${repair.repairNo}" style="--card-index:${index}" aria-label="查看 ${repair.factory} 返修进度详情">
        <span class="repair-progress-card__heading">
          <span><small>工厂</small><strong>${repair.factory}</strong><em>${productSummary}</em></span>
          <span class="repair-progress-card__pending"><small>待返回</small><strong>${formatNumber(pendingQuantity)}件</strong></span>
        </span>
        <span class="repair-progress-card__progress">
          <span><small>返回进度</small><strong>${formatNumber(returnedQuantity)} / ${formatNumber(repair.warehouseReturnQuantity)}</strong><em>${progress}%</em></span>
          <i><b style="width:${progress}%"></b></i>
        </span>
        <span class="repair-progress-card__stats">
          <span><small>返修数量</small><strong>${formatNumber(repair.repairedQuantity)}</strong></span>
          <span><small>报废数量</small><strong>${formatNumber(repair.scrappedQuantity)}</strong></span>
        </span>
        <span class="repair-progress-card__date"><i>${icons.calendar}</i><small>退回日期</small><strong>${repair.returnDate}</strong></span>
        <span class="repair-progress-card__number"><small>返修单号</small><strong>${repair.repairNo}</strong></span>
      </button>
    `;
  }

  function renderFilterSheet(context, factories) {
    const { icons, state, helpers } = context;
    if (!state.repairFilterOpen) return "";
    return `
      <div class="sheet-layer" data-close-repair-sheet>
        <section class="filter-sheet" role="dialog" aria-modal="true" aria-labelledby="repair-filter-title">
          <div class="sheet-handle" aria-hidden="true"></div>
          <header class="filter-sheet__header">
            <div><p>移动筛选</p><h2 id="repair-filter-title">筛选返修进度</h2></div>
            <button type="button" class="icon-button" data-close-repair-sheet aria-label="关闭筛选">${icons.close}</button>
          </header>
          <div class="filter-sheet__body">
            <label class="field">
              <span>工厂</span>
              <select id="repair-filter-factory">
                ${helpers.selectOptions([["all", "全部工厂"], ...factories.map((factory) => [factory, factory])], state.repairFactories[0] ?? "all")}
              </select>
            </label>
            <fieldset class="field date-field">
              <legend>退回日期范围</legend>
              <div>
                <input id="repair-date-start" type="date" value="${state.repairDateStart}" aria-label="退回开始日期" />
                <span>至</span>
                <input id="repair-date-end" type="date" value="${state.repairDateEnd}" aria-label="退回结束日期" />
              </div>
            </fieldset>
          </div>
          <footer class="filter-sheet__actions">
            <button type="button" class="secondary-button" id="reset-repair-filter">重置</button>
            <button type="button" class="primary-button" id="apply-repair-filter">查看结果</button>
          </footer>
        </section>
      </div>
    `;
  }

  function bindEvents(context) {
    const { state, render, navigate, helpers } = context;
    document.querySelector("#repair-search")?.addEventListener("input", (event) => {
      state.repairKeyword = event.target.value;
      render();
      const input = document.querySelector("#repair-search");
      input?.focus();
      input?.setSelectionRange(state.repairKeyword.length, state.repairKeyword.length);
    });

    document.querySelector("#open-repair-filter")?.addEventListener("click", () => {
      state.repairFilterOpen = true;
      render();
    });

    document.querySelectorAll("[data-close-repair-sheet]").forEach((element) => {
      element.addEventListener("click", (event) => {
        if (event.target.closest(".filter-sheet") && !event.target.closest(".icon-button")) return;
        state.repairFilterOpen = false;
        render();
      });
    });

    document.querySelector("#reset-repair-filter")?.addEventListener("click", () => {
      Object.assign(state, { repairFactories: [], repairDateStart: "", repairDateEnd: "" });
      render();
    });

    document.querySelector("#apply-repair-filter")?.addEventListener("click", () => {
      const factory = document.querySelector("#repair-filter-factory").value;
      state.repairFactories = factory === "all" ? [] : [factory];
      state.repairDateStart = document.querySelector("#repair-date-start").value;
      state.repairDateEnd = document.querySelector("#repair-date-end").value;
      state.repairFilterOpen = false;
      render();
    });

    document.querySelector("#clear-repair-filters")?.addEventListener("click", () => {
      Object.assign(state, { repairKeyword: "", repairFactories: [], repairDateStart: "", repairDateEnd: "" });
      render();
    });

    document.querySelectorAll("[data-repair-no]").forEach((button) => {
      button.addEventListener("click", () => navigate("repair-detail", { selectedRepairNo: button.dataset.repairNo }));
    });

    document.querySelector("[data-page-target='orders']")?.addEventListener("click", () => navigate("orders"));
    document.querySelector("[data-page-target='shipments']")?.addEventListener("click", () => navigate("shipments"));
    document.querySelector("[data-page-target='profile']")?.addEventListener("click", () => navigate("profile"));
    document.querySelectorAll("[data-prototype-target]").forEach((button) => {
      button.addEventListener("click", () => helpers.showToast(`${button.dataset.prototypeTarget}页面将在逐项确认后制作`));
    });
  }

  function mount(context) {
    const { app, data, icons, state, helpers } = context;
    const factories = [...new Set(data.repairRecords.map((repair) => repair.factory))];
    const visibleRepairs = getVisibleRepairs(data, state);
    const activeFilterCount = [
      state.repairFactories.length > 0,
      Boolean(state.repairDateStart),
      Boolean(state.repairDateEnd),
    ].filter(Boolean).length;

    app.innerHTML = `
      <div class="page-shell repair-list-page">
        <header class="page-header">
          <div class="mini-titlebar">
            <span class="titlebar-spacer" aria-hidden="true"></span>
            <h1>发货</h1>
            <div class="wechat-capsule" aria-hidden="true"><b>•••</b><i></i><span></span></div>
          </div>
          <div class="shipment-segmented" role="tablist" aria-label="发货板块">
            <button type="button" role="tab" aria-selected="false" data-page-target="shipments">发货记录</button>
            <button type="button" class="is-active" role="tab" aria-selected="true">返修进度</button>
          </div>
          <div class="search-row">
            <label class="search-box">
              ${icons.search}
              <input id="repair-search" type="search" value="${state.repairKeyword}" placeholder="工厂名称" autocomplete="off" />
            </label>
            <button type="button" class="filter-button" id="open-repair-filter">
              ${icons.filter}<span>筛选</span>${activeFilterCount ? `<b>${activeFilterCount}</b>` : ""}
            </button>
          </div>
        </header>

        <section class="repair-progress-list" aria-label="返修进度列表">
          <div class="result-summary"><span>共 ${visibleRepairs.length} 家工厂</span><em>按退回日期倒序</em></div>
          ${
            visibleRepairs.length
              ? visibleRepairs.map((repair, index) => renderRepairCard(repair, index, icons, helpers.formatNumber, data.repairDetails)).join("")
              : `<div class="empty-state"><span>${icons.search}</span><h2>没有符合条件的返修记录</h2><p>可以调整工厂名称或筛选条件后再试。</p><button id="clear-repair-filters" type="button">清除筛选</button></div>`
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
  window.AdminPrototypePages.repairs = { mount };
})();
