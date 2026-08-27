(function registerOrderListPage() {
  function getOrderDisplayStatus(order) {
    if (order.status === "draft") return { key: "draft", label: "草稿", tone: "draft" };
    if (order.status === "completed") return { key: "completed", label: "已完成", tone: "completed" };
    if (order.overdueDays > 0) return { key: "overdue", label: "已逾期", tone: "overdue" };
    return { key: "incomplete", label: "未完成", tone: "incomplete" };
  }

  function getVisibleOrders(data, state) {
    const keyword = state.keyword.trim().toLowerCase();
    const filtered = data.orders.filter((order) => {
      const matchesKeyword =
        !keyword ||
        order.orderNo.toLowerCase().includes(keyword) ||
        order.productName.toLowerCase().includes(keyword);
      const matchesStatus = state.status === "all" || getOrderDisplayStatus(order).key === state.status;
      const matchesFactory = !state.factories.length || order.factories.some((factory) => state.factories.includes(factory));
      const matchesTracker = state.tracker === "all" || order.tracker === state.tracker;
      const matchesStart = !state.dueStart || order.contractShipDate >= state.dueStart;
      const matchesEnd = !state.dueEnd || order.contractShipDate <= state.dueEnd;
      return matchesKeyword && matchesStatus && matchesFactory && matchesTracker && matchesStart && matchesEnd;
    });

    return filtered.sort((a, b) => {
      if (state.sort === "due-asc") return a.contractShipDate.localeCompare(b.contractShipDate);
      if (state.sort === "due-desc") return b.contractShipDate.localeCompare(a.contractShipDate);
      if (state.sort === "order-newest") return b.orderDate.localeCompare(a.orderDate);
      if (state.sort === "updated-newest") return b.updatedAt.localeCompare(a.updatedAt);

      const urgency = (order) => {
        if (order.overdueDays > 0 && order.status !== "completed") return 0;
        if (["pending", "shipping"].includes(order.status)) return 1;
        if (order.status === "draft") return 2;
        return 3;
      };
      return urgency(a) - urgency(b) || a.contractShipDate.localeCompare(b.contractShipDate);
    });
  }

  function renderOrderCard(order, index, icons, formatNumber) {
    const unshipped = Math.max(order.total - order.shipped, 0);
    const displayStatus = getOrderDisplayStatus(order);
    return `
      <article class="order-card" style="--card-index:${index}" role="button" tabindex="0" aria-label="查看订单 ${order.orderNo} 详情" data-order-id="${order.id}">
        <div class="order-card__heading">
          <div>
            <p class="order-card__number">${order.orderNo}</p>
            <h2>${order.productName}</h2>
          </div>
          <div class="order-card__badges">
            <span class="status status--${displayStatus.tone}">${displayStatus.label}</span>
          </div>
        </div>

        <div class="order-card__facts">
          <p><span class="fact-icon">${icons.user}</span><span class="fact-label">跟单人员</span><strong>${order.tracker}</strong></p>
          <p><span class="fact-icon">${icons.factory}</span><span class="fact-label">工厂</span><strong>${order.factories.join("、")}</strong></p>
        </div>

        <div class="order-card__due ${order.overdueDays > 0 ? "order-card__due--overdue" : ""}">
          <span class="fact-icon">${icons.calendar}</span>
          <span>合同出货时间</span>
          <strong>${order.contractShipDateLabel}</strong>
        </div>

        <div class="order-card__quantities">
          <div><span>下单</span><strong>${formatNumber(order.total)}</strong></div>
          <div><span>已发</span><strong>${formatNumber(order.shipped)}</strong></div>
          <div><span>未发</span><strong class="${unshipped > 0 ? "pending-value--warn" : ""}">${formatNumber(unshipped)}</strong></div>
        </div>

        <div class="order-card__progress">
          <div class="progress-track"><i style="width:${order.progress}%"></i></div>
          <strong>${order.progress}%</strong>
        </div>
      </article>
    `;
  }

  function renderFilterSheet(context, factories, trackers) {
    const { data, icons, state, helpers } = context;
    if (!state.filterOpen) return "";
    return `
      <div class="sheet-layer" data-close-sheet>
        <section class="filter-sheet" role="dialog" aria-modal="true" aria-labelledby="filter-title">
          <div class="sheet-handle" aria-hidden="true"></div>
          <header class="filter-sheet__header">
            <div><p>移动筛选</p><h2 id="filter-title">筛选订单</h2></div>
            <button type="button" class="icon-button" data-close-sheet aria-label="关闭筛选">${icons.close}</button>
          </header>

          <div class="filter-sheet__body">
            <label class="field">
              <span>订单状态</span>
              <select id="filter-status">${helpers.selectOptions(data.statusOptions, state.status)}</select>
            </label>
            <label class="field">
              <span>工厂</span>
              <select id="filter-factory">
                ${helpers.selectOptions([["all", "全部工厂"], ...factories.map((name) => [name, name])], state.factories[0] ?? "all")}
              </select>
            </label>
            <label class="field">
              <span>跟单人员</span>
              <select id="filter-tracker">
                ${helpers.selectOptions([["all", "全部跟单人员"], ...trackers.map((name) => [name, name])], state.tracker)}
              </select>
            </label>
            <fieldset class="field date-field">
              <legend>合同出货时间范围</legend>
              <div>
                <input id="filter-date-start" type="date" value="${state.dueStart}" aria-label="合同出货开始日期" />
                <span>至</span>
                <input id="filter-date-end" type="date" value="${state.dueEnd}" aria-label="合同出货结束日期" />
              </div>
            </fieldset>
            <label class="field">
              <span>排序方式</span>
              <select id="filter-sort">${helpers.selectOptions(data.sortOptions, state.sort)}</select>
            </label>
          </div>

          <footer class="filter-sheet__actions">
            <button type="button" class="secondary-button" id="reset-filter">重置</button>
            <button type="button" class="primary-button" id="apply-filter">查看结果</button>
          </footer>
        </section>
      </div>
    `;
  }

  function bindEvents(context) {
    const { state, render, navigate, helpers } = context;
    document.querySelector("#order-search")?.addEventListener("input", (event) => {
      state.keyword = event.target.value;
      render();
      const input = document.querySelector("#order-search");
      input?.focus();
      input?.setSelectionRange(state.keyword.length, state.keyword.length);
    });

    document.querySelector("#open-filter")?.addEventListener("click", () => {
      state.filterOpen = true;
      render();
    });

    document.querySelectorAll("[data-close-sheet]").forEach((element) => {
      element.addEventListener("click", (event) => {
        if (event.target.closest(".filter-sheet") && !event.target.closest(".icon-button")) return;
        state.filterOpen = false;
        render();
      });
    });

    document.querySelector("#reset-filter")?.addEventListener("click", () => {
      Object.assign(state, {
        status: "all",
        factories: [],
        tracker: "all",
        dueStart: "",
        dueEnd: "",
        sort: "urgent",
      });
      render();
    });

    document.querySelector("#apply-filter")?.addEventListener("click", () => {
      state.status = document.querySelector("#filter-status").value;
      const factory = document.querySelector("#filter-factory").value;
      state.factories = factory === "all" ? [] : [factory];
      state.tracker = document.querySelector("#filter-tracker").value;
      state.dueStart = document.querySelector("#filter-date-start").value;
      state.dueEnd = document.querySelector("#filter-date-end").value;
      state.sort = document.querySelector("#filter-sort").value;
      state.filterOpen = false;
      render();
    });

    document.querySelector("#clear-all")?.addEventListener("click", () => {
      Object.assign(state, {
        keyword: "",
        status: "all",
        factories: [],
        tracker: "all",
        dueStart: "",
        dueEnd: "",
        sort: "urgent",
      });
      render();
    });

    document.querySelectorAll("[data-order-id]").forEach((card) => {
      const openOrder = () => navigate("order-detail", { selectedOrderId: card.dataset.orderId, orderBackPage: "orders" });
      card.addEventListener("click", openOrder);
      card.addEventListener("keydown", (event) => {
        if (!["Enter", " "].includes(event.key)) return;
        event.preventDefault();
        openOrder();
      });
    });

    document.querySelector("[data-page-target='shipments']")?.addEventListener("click", () => navigate("shipments"));
    document.querySelector("[data-page-target='profile']")?.addEventListener("click", () => navigate("profile"));

    document.querySelectorAll("[data-prototype-target]").forEach((button) => {
      button.addEventListener("click", () => helpers.showToast(`${button.dataset.prototypeTarget}页面将在逐项确认后制作`));
    });
  }

  function mount(context) {
    const { app, data, icons, state, helpers } = context;
    const factories = [...new Set(data.orders.flatMap((order) => order.factories))];
    const trackers = [...new Set(data.orders.map((order) => order.tracker))];
    const visibleOrders = getVisibleOrders(data, state);
    const activeFilterCount = [
      state.status !== "all",
      state.factories.length > 0,
      state.tracker !== "all",
      Boolean(state.dueStart),
      Boolean(state.dueEnd),
      state.sort !== "urgent",
    ].filter(Boolean).length;

    app.innerHTML = `
      <div class="page-shell">
        <header class="page-header">
          <div class="mini-titlebar">
            <span class="titlebar-spacer" aria-hidden="true"></span>
            <h1>订单</h1>
            <div class="wechat-capsule" aria-hidden="true"><b>•••</b><i></i><span></span></div>
          </div>
          <div class="search-row">
            <label class="search-box">
              ${icons.search}
              <input id="order-search" type="search" value="${state.keyword}" placeholder="订单编号、产品名称" autocomplete="off" />
            </label>
            <button type="button" class="filter-button" id="open-filter">
              ${icons.filter}<span>筛选</span>${activeFilterCount ? `<b>${activeFilterCount}</b>` : ""}
            </button>
          </div>
        </header>

        <section class="order-list" aria-label="订单列表">
          <div class="result-summary"><span>共 ${visibleOrders.length} 个订单</span></div>
          ${
            visibleOrders.length
              ? visibleOrders.map((order, index) => renderOrderCard(order, index, icons, helpers.formatNumber)).join("")
              : `<div class="empty-state"><span>${icons.search}</span><h2>没有符合条件的订单</h2><p>可以调整搜索词或筛选条件后再试。</p><button id="clear-all" type="button">清除筛选</button></div>`
          }
        </section>

        <nav class="tabbar" aria-label="管理员小程序一级导航">
          <button type="button" class="tabbar__item is-active">${icons.orders}<span>订单</span></button>
          <button type="button" class="tabbar__item" data-page-target="shipments">${icons.truck}<span>发货</span></button>
          <button type="button" class="tabbar__item" data-page-target="profile">${icons.profile}<span>我的</span></button>
        </nav>
      </div>
      ${renderFilterSheet(context, factories, trackers)}
      <div class="prototype-toast" role="status"></div>
    `;

    bindEvents(context);
  }

  window.AdminPrototypePages ??= {};
  window.AdminPrototypePages.orders = { mount };
})();
