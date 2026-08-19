(function registerShipmentRecordsPage() {
  function escapeHtml(value) {
    return String(value).replace(/[&<>'"]/g, function (char) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" }[char];
    });
  }

  function formatNumber(value) {
    return Number(value).toLocaleString("zh-CN");
  }

  function productSummary(names) {
    return names.length > 1 ? names[0] + "等" + names.length + "个产品" : names[0];
  }

  function orderSummary(orderNos) {
    return orderNos.join("、");
  }

  function mount(app, initialKind) {
    var data = window.FactoryPrototypeData;
    var icons = window.FactoryIcons;
    var state = { keyword: "", start: "", end: "", filterOpen: false };

    function currentRecords() {
      var keyword = state.keyword.trim().toLowerCase();
      return data.shipmentRecords.filter(function (record) {
        var searchable = record.orderNos.concat(record.productNames).join(" ");
        return (!keyword || searchable.toLowerCase().includes(keyword)) &&
          (!state.start || record.shipDate >= state.start) &&
          (!state.end || record.shipDate <= state.end);
      }).sort(function (a, b) { return b.shipDate.localeCompare(a.shipDate); });
    }

    function renderOrderCard(record, index) {
      return '<button type="button" class="record-card" data-record-id="' + escapeHtml(record.id) + '" data-record-detail="订单发货单详情" style="--card-index:' + index + '">' +
        '<span class="record-card__heading"><span><strong>' + escapeHtml(productSummary(record.productNames)) + '　' + escapeHtml(orderSummary(record.orderNos)) + '</strong></span><i>' + icons.chevron + '</i></span>' +
        '<span class="record-card__date"><span>' + icons.calendar + '发货日期</span><strong>' + escapeHtml(record.shipDate) + '</strong></span>' +
        '<span class="record-card__stats"><span><small>发货数量</small><strong>' + formatNumber(record.totalQuantity) + '</strong></span><span><small>总箱数</small><strong>' + formatNumber(record.totalBoxes) + '</strong></span></span>' +
        '<span class="record-card__number"><small>发货单号</small><strong>' + escapeHtml(record.shipmentNo) + '</strong></span>' +
      '</button>';
    }

    function renderFilterSheet() {
      if (!state.filterOpen) return "";
      return '<div class="sheet-layer" data-close-record-filter>' +
        '<section class="filter-sheet" role="dialog" aria-modal="true" aria-labelledby="record-filter-title">' +
          '<div class="sheet-handle" aria-hidden="true"></div>' +
          '<header class="filter-sheet__header"><div><p>工厂小程序</p><h2 id="record-filter-title">筛选发货记录</h2></div><button type="button" class="icon-button" data-close-record-filter aria-label="关闭筛选">' + icons.close + '</button></header>' +
          '<div class="filter-sheet__body"><fieldset class="field date-field"><legend>发货日期范围</legend><div><input id="record-date-start" type="date" value="' + state.start + '" aria-label="开始日期" /><span>至</span><input id="record-date-end" type="date" value="' + state.end + '" aria-label="结束日期" /></div></fieldset></div>' +
          '<footer class="filter-sheet__actions"><button type="button" class="secondary-button" id="reset-record-filter">重置</button><button type="button" class="primary-button" id="apply-record-filter">查看结果</button></footer>' +
        '</section></div>';
    }

    function render() {
      var records = currentRecords();
      var hasDateFilter = Boolean(state.start || state.end);
      app.innerHTML = '<div class="page-shell shipment-records-page">' +
        '<header class="page-header"><div class="mini-titlebar"><span class="titlebar-spacer" aria-hidden="true"></span><h1>发货记录</h1><div class="wechat-capsule" aria-hidden="true"><b>•••</b><i></i><span></span></div></div>' +
        '<div class="search-row"><label class="search-box">' + icons.search + '<input id="record-search" type="search" value="' + escapeHtml(state.keyword) + '" placeholder="订单编号或产品名称" autocomplete="off" /></label><button type="button" class="filter-button" id="open-record-filter">' + icons.filter + '<span>筛选</span>' + (hasDateFilter ? '<b>1</b>' : '') + '</button></div></header>' +
        '<section class="shipment-record-list"><div class="result-summary"><span>共 ' + records.length + ' 张发货单</span></div>' +
        (records.length ? records.map(function (record, index) { return renderOrderCard(record, index); }).join("") : '<div class="empty-state"><span>' + icons.search + '</span><h2>没有符合条件的记录</h2><p>可以调整搜索词或日期后再试。</p><button id="clear-record-filter" type="button">清除筛选</button></div>') + '</section>' +
        '<nav class="tabbar" aria-label="工厂小程序一级导航"><button type="button" class="tabbar__item" id="back-to-tasks">' + icons.tasks + '<span>任务</span></button><button type="button" class="tabbar__item is-active">' + icons.truck + '<span>发货记录</span></button><button type="button" class="tabbar__item" id="open-profile">' + icons.profile + '<span>我的</span></button></nav></div>' +
        renderFilterSheet() + '<div class="prototype-toast" role="status"></div>';
      bindEvents();
    }

    function showToast(message) {
      var toast = document.querySelector(".prototype-toast");
      if (!toast) return;
      toast.textContent = message;
      toast.classList.remove("is-visible");
      void toast.offsetWidth;
      toast.classList.add("is-visible");
      setTimeout(function () { toast.classList.remove("is-visible"); }, 1800);
    }

    function bindEvents() {
      document.querySelector("#record-search")?.addEventListener("input", function (event) {
        state.keyword = event.target.value;
        render();
        var input = document.querySelector("#record-search");
        input?.focus();
        input?.setSelectionRange(state.keyword.length, state.keyword.length);
      });
      document.querySelector("#open-record-filter")?.addEventListener("click", function () { state.filterOpen = true; render(); });
      document.querySelectorAll("[data-close-record-filter]").forEach(function (element) {
        element.addEventListener("click", function (event) {
          if (event.target.closest(".filter-sheet") && !event.target.closest(".icon-button")) return;
          state.filterOpen = false; render();
        });
      });
      document.querySelector("#reset-record-filter")?.addEventListener("click", function () { state.start = ""; state.end = ""; render(); });
      document.querySelector("#apply-record-filter")?.addEventListener("click", function () {
        state.start = document.querySelector("#record-date-start").value;
        state.end = document.querySelector("#record-date-end").value;
        state.filterOpen = false; render();
      });
      document.querySelector("#clear-record-filter")?.addEventListener("click", function () { state.keyword = ""; state.start = ""; state.end = ""; render(); });
      document.querySelectorAll("[data-record-detail]").forEach(function (button) {
        button.addEventListener("click", function () {
          var page = window.FactoryPages["shipment-detail"];
          if (page && page.mount) page.mount(app, button.closest("[data-record-id]")?.dataset.recordId);
        });
      });
      document.querySelector("#back-to-tasks")?.addEventListener("click", function () { window.FactoryPages["task-list"].mount(app); });
      document.querySelector("#open-profile")?.addEventListener("click", function () { window.FactoryPages.profile.mount(app); });
      document.querySelectorAll("[data-prototype-target]").forEach(function (button) { button.addEventListener("click", function () { showToast(button.dataset.prototypeTarget + "页面将在逐项确认后制作"); }); });
    }

    render();
  }

  window.FactoryPages ??= {};
  window.FactoryPages["shipment-records"] = { mount: mount };
})();
