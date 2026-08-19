(function registerTaskList() {
  function getOrderDisplayStatus(task) {
    if (task.status === "completed") return { key: "completed", label: "已完成", tone: "completed" };
    if (task.overdueDays > 0) return { key: "overdue", label: "已逾期", tone: "overdue" };
    return { key: "incomplete", label: "未完成", tone: "incomplete" };
  }

  function getVisibleOrderTasks(data, filter) {
    var keyword = filter.keyword.trim().toLowerCase();
    var filtered = data.tasks.filter(function (task) {
      var matchesKeyword =
        !keyword ||
        task.orderNo.toLowerCase().includes(keyword) ||
        task.productSummary.toLowerCase().includes(keyword) ||
        task.specSummary.toLowerCase().includes(keyword);
      var matchesStatus = filter.status === "all" || getOrderDisplayStatus(task).key === filter.status;
      var matchesStart = !filter.start || task.contractShipDate >= filter.start;
      var matchesEnd = !filter.end || task.contractShipDate <= filter.end;
      return matchesKeyword && matchesStatus && matchesStart && matchesEnd;
    });

    return filtered.sort(function (a, b) {
      var aUrgency = a.overdueDays > 0 && a.status !== "completed" ? 0 : a.status === "completed" ? 2 : 1;
      var bUrgency = b.overdueDays > 0 && b.status !== "completed" ? 0 : b.status === "completed" ? 2 : 1;
      if (aUrgency !== bUrgency) return aUrgency - bUrgency;
      return a.contractShipDate.localeCompare(b.contractShipDate);
    });
  }

  function getVisibleRepairTasks(data, filter) {
    var keyword = filter.keyword.trim().toLowerCase();
    var filtered = data.repairTasks.filter(function (task) {
      var matchesKeyword =
        !keyword ||
        task.repairNo.toLowerCase().includes(keyword) ||
        task.productNames.some(function (name) { return name.toLowerCase().includes(keyword); });
      var matchesStatus =
        filter.status === "all" ||
        (filter.status === "incomplete" ? task.status !== "completed" : task.status === filter.status);
      var matchesStart = !filter.start || task.returnDate >= filter.start;
      var matchesEnd = !filter.end || task.returnDate <= filter.end;
      return !task.archived && matchesKeyword && matchesStatus && matchesStart && matchesEnd;
    });

    var statusRank = { pending: 0, processing: 1, completed: 2 };
    return filtered.sort(function (a, b) {
      return statusRank[a.status] - statusRank[b.status] || a.returnDate.localeCompare(b.returnDate);
    });
  }

  function renderOrderCard(task, index, icons) {
    var displayStatus = getOrderDisplayStatus(task);
    return (
      '<article class="order-card" style="--card-index:' + index + '" role="button" tabindex="0" aria-label="查看任务 ' + escapeHtml(task.orderNo) + ' 详情" data-task-id="' + task.id + '">' +
        '<div class="order-card__heading">' +
          '<div><p class="order-card__number">' + escapeHtml(task.orderNo) + '</p><h2>' + escapeHtml(task.productSummary) + '</h2></div>' +
          '<div class="order-card__badges">' +
            '<span class="status status--' + displayStatus.tone + '">' + displayStatus.label + '</span>' +
          '</div>' +
        '</div>' +
        '<div class="order-card__due' + (task.overdueDays > 0 && task.status !== "completed" ? " order-card__due--overdue" : "") + '">' +
          '<span class="fact-icon">' + icons.calendar + '</span><span>合同出货时间</span><strong>' + escapeHtml(task.contractShipDateLabel) + '</strong>' +
        '</div>' +
        '<div class="order-card__quantities">' +
          '<div><span>下单</span><strong>' + formatNumber(task.totalAllocated) + '</strong></div>' +
          '<div><span>已发</span><strong>' + formatNumber(task.totalShipped) + '</strong></div>' +
          '<div><span>未发</span><strong class="' + (task.totalPending > 0 ? "pending-value--warn" : "") + '">' + formatNumber(task.totalPending) + '</strong></div>' +
        '</div>' +
        '<div class="order-card__progress"><div class="progress-track"><i style="width:' + task.progress + '%"></i></div><strong>' + task.progress + '%</strong></div>' +
      '</article>'
    );
  }

  function renderRepairCard(task, index, icons) {
    return (
      '<article class="order-card repair-card" style="--card-index:' + index + '" role="button" tabindex="0" aria-label="查看返修任务 ' + escapeHtml(task.repairNo) + ' 详情" data-repair-id="' + task.id + '">' +
        '<div class="order-card__heading">' +
          '<div><p class="repair-card__number">' + escapeHtml(task.repairNo) + '</p><h2>' + escapeHtml(task.productSummary) + '</h2></div>' +
          '<div class="order-card__badges"><span class="status status--' + (task.status === "completed" ? "completed" : "incomplete") + '">' + (task.status === "completed" ? "已完成" : "未完成") + '</span></div>' +
        '</div>' +
        '<div class="order-card__due repair-card__date">' +
          '<span class="fact-icon">' + icons.calendar + '</span><span>退回日期</span><strong>' + escapeHtml(task.returnDateLabel) + '</strong>' +
        '</div>' +
        '<div class="order-card__quantities repair-card__quantities">' +
          '<div><span>仓库退回</span><strong>' + formatNumber(task.warehouseReturned) + '</strong></div>' +
          '<div><span>已返回</span><strong>' + formatNumber(task.returned) + '</strong></div>' +
          '<div><span>待返回</span><strong class="' + (task.pendingReturn > 0 ? "pending-value--warn" : "") + '">' + formatNumber(task.pendingReturn) + '</strong></div>' +
        '</div>' +
        '<div class="repair-card__progress"><span>返回进度</span><div class="progress-track"><i style="width:' + task.progress + '%"></i></div><strong>' + task.progress + '%</strong></div>' +
      '</article>'
    );
  }

  function escapeHtml(value) {
    var div = document.createElement("div");
    div.appendChild(document.createTextNode(value == null ? "" : String(value)));
    return div.innerHTML;
  }

  function formatNumber(value) {
    return Number(value || 0).toString().replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  }

  function mount(app, initialKind) {
    var data = window.FactoryPrototypeData;
    var icons = window.FactoryIcons;
    var state = {
      activeKind: initialKind === "repair" ? "repair" : "order",
      filterOpen: false,
      filters: {
        order: { keyword: "", status: "all", start: "", end: "" },
        repair: { keyword: "", status: "incomplete", start: "", end: "" },
      },
    };

    function getActiveFilter() {
      return state.filters[state.activeKind];
    }

    function getDefaultStatus() {
      return state.activeKind === "order" ? "all" : "incomplete";
    }

    function render() {
      var isOrder = state.activeKind === "order";
      var filter = getActiveFilter();
      var visible = isOrder ? getVisibleOrderTasks(data, filter) : getVisibleRepairTasks(data, filter);
      var activeFilterCount = [
        filter.status !== getDefaultStatus(),
        Boolean(filter.start),
        Boolean(filter.end),
      ].filter(Boolean).length;

      app.innerHTML =
        '<div class="page-shell">' +
          '<header class="page-header">' +
            '<div class="mini-titlebar"><span class="titlebar-spacer" aria-hidden="true"></span><h1>任务</h1><div class="wechat-capsule" aria-hidden="true"><b>•••</b><i></i><span></span></div></div>' +
            '<div class="task-kind-tabs" role="tablist" aria-label="任务类型">' +
              '<button type="button" role="tab" class="task-kind-tab' + (isOrder ? " is-active" : "") + '" aria-selected="' + isOrder + '" data-task-kind="order">订单</button>' +
              '<button type="button" role="tab" class="task-kind-tab' + (!isOrder ? " is-active" : "") + '" aria-selected="' + (!isOrder) + '" data-task-kind="repair">返修</button>' +
            '</div>' +
            '<div class="search-row">' +
              '<label class="search-box">' + icons.search + '<input id="task-search" type="search" value="' + escapeHtml(filter.keyword) + '" placeholder="' + (isOrder ? "订单编号或产品名称" : "返修单号或产品名称") + '" autocomplete="off" /></label>' +
              '<button type="button" class="filter-button" id="open-filter">' + icons.filter + '<span>筛选</span>' + (activeFilterCount ? '<b>' + activeFilterCount + '</b>' : "") + '</button>' +
            '</div>' +
          '</header>' +
          '<section class="order-list' + (!isOrder ? " order-list--repair" : "") + '" aria-label="' + (isOrder ? "订单任务列表" : "返修任务列表") + '">' +
            '<div class="result-summary"><span>共 ' + visible.length + ' 个' + (isOrder ? "订单" : "返修") + '任务</span></div>' +
            (visible.length
              ? visible.map(function (task, index) { return isOrder ? renderOrderCard(task, index, icons) : renderRepairCard(task, index, icons); }).join("")
              : '<div class="empty-state"><span>' + icons.search + '</span><h2>没有符合条件的' + (isOrder ? "订单" : "返修") + '任务</h2><p>可以调整搜索词或筛选条件后再试。</p><button id="clear-all" type="button">清除筛选</button></div>') +
            (isOrder ? '<div class="create-shipment-bar"><button type="button" class="primary-button create-shipment-btn" id="create-shipment-btn">创建发货单</button></div>' : "") +
          '</section>' +
          '<nav class="tabbar" aria-label="工厂小程序一级导航">' +
            '<button type="button" class="tabbar__item is-active">' + icons.tasks + '<span>任务</span></button>' +
            '<button type="button" class="tabbar__item" id="open-shipment-records">' + icons.truck + '<span>发货记录</span></button>' +
            '<button type="button" class="tabbar__item" id="open-profile">' + icons.profile + '<span>我的</span></button>' +
          '</nav>' +
        '</div>' +
        renderFilterSheet() +
        '<div class="prototype-toast" role="status"></div>';

      bindEvents();
    }

    function renderFilterSheet() {
      if (!state.filterOpen) return "";
      var isOrder = state.activeKind === "order";
      var filter = getActiveFilter();
      var options = isOrder ? data.statusOptions : data.repairStatusOptions;
      return (
        '<div class="sheet-layer" data-close-sheet>' +
          '<section class="filter-sheet" role="dialog" aria-modal="true" aria-labelledby="filter-title">' +
            '<div class="sheet-handle" aria-hidden="true"></div>' +
            '<header class="filter-sheet__header"><div><p>工厂小程序</p><h2 id="filter-title">筛选' + (isOrder ? "订单" : "返修") + '任务</h2></div><button type="button" class="icon-button" data-close-sheet aria-label="关闭筛选">' + icons.close + '</button></header>' +
            '<div class="filter-sheet__body">' +
              '<label class="field"><span>' + (isOrder ? "订单" : "返修") + '状态</span><select id="filter-status">' +
                options.map(function (option) { return '<option value="' + option[0] + '"' + (option[0] === filter.status ? " selected" : "") + '>' + option[1] + '</option>'; }).join("") +
              '</select></label>' +
              '<fieldset class="field date-field"><legend>' + (isOrder ? "合同出货时间" : "退回日期") + '范围</legend><div>' +
                '<input id="filter-date-start" type="date" value="' + filter.start + '" aria-label="开始日期" /><span>至</span><input id="filter-date-end" type="date" value="' + filter.end + '" aria-label="结束日期" />' +
              '</div></fieldset>' +
            '</div>' +
            '<footer class="filter-sheet__actions"><button type="button" class="secondary-button" id="reset-filter">重置</button><button type="button" class="primary-button" id="apply-filter">查看结果</button></footer>' +
          '</section>' +
        '</div>'
      );
    }

    function bindEvents() {
      document.querySelectorAll("[data-task-kind]").forEach(function (button) {
        button.addEventListener("click", function () {
          state.activeKind = button.dataset.taskKind;
          state.filterOpen = false;
          render();
        });
      });

      document.querySelector("#task-search")?.addEventListener("input", function (event) {
        getActiveFilter().keyword = event.target.value;
        render();
        var input = document.querySelector("#task-search");
        input?.focus();
        input?.setSelectionRange(getActiveFilter().keyword.length, getActiveFilter().keyword.length);
      });

      document.querySelector("#open-filter")?.addEventListener("click", function () {
        state.filterOpen = true;
        render();
      });

      document.querySelectorAll("[data-close-sheet]").forEach(function (element) {
        element.addEventListener("click", function (event) {
          if (event.target.closest(".filter-sheet") && !event.target.closest(".icon-button")) return;
          state.filterOpen = false;
          render();
        });
      });

      document.querySelector("#reset-filter")?.addEventListener("click", function () {
        var filter = getActiveFilter();
        filter.status = getDefaultStatus();
        filter.start = "";
        filter.end = "";
        render();
      });

      document.querySelector("#apply-filter")?.addEventListener("click", function () {
        var filter = getActiveFilter();
        filter.status = document.querySelector("#filter-status").value;
        filter.start = document.querySelector("#filter-date-start").value;
        filter.end = document.querySelector("#filter-date-end").value;
        state.filterOpen = false;
        render();
      });

      document.querySelector("#clear-all")?.addEventListener("click", function () {
        state.filters[state.activeKind] = { keyword: "", status: getDefaultStatus(), start: "", end: "" };
        render();
      });

      document.querySelector("#create-shipment-btn")?.addEventListener("click", function () {
        var page = window.FactoryPages["create-shipment"];
        if (page && page.mount) page.mount(app);
      });

      document.querySelector("#open-shipment-records")?.addEventListener("click", function () {
        var page = window.FactoryPages["shipment-records"];
        if (page && page.mount) page.mount(app, "order");
      });

      document.querySelector("#open-profile")?.addEventListener("click", function () {
        var page = window.FactoryPages.profile;
        if (page && page.mount) page.mount(app);
      });

      document.querySelectorAll(".order-card[data-task-id]").forEach(function (card) {
        function openTaskDetail() {
          var page = window.FactoryPages["task-detail"];
          if (page && page.mount) page.mount(app, card.dataset.taskId);
        }
        card.addEventListener("click", openTaskDetail);
        card.addEventListener("keydown", function (event) {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            openTaskDetail();
          }
        });
      });

      document.querySelectorAll(".repair-card[data-repair-id]").forEach(function (card) {
        function openRepairDetail() {
          var page = window.FactoryPages["repair-detail"];
          if (page && page.mount) page.mount(app, card.dataset.repairId);
        }
        card.addEventListener("click", openRepairDetail);
        card.addEventListener("keydown", function (event) {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            openRepairDetail();
          }
        });
      });

      document.querySelectorAll("[data-prototype-target]").forEach(function (button) {
        button.addEventListener("click", function () { showToast(button.dataset.prototypeTarget + "页面将在逐项确认后制作"); });
      });
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

    render();
  }

  window.FactoryPages ??= {};
  window.FactoryPages["task-list"] = { mount: mount };
})();
