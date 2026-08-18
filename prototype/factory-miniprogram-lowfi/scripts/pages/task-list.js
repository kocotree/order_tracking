(function registerTaskList() {
  function getVisibleTasks(data, state) {
    var keyword = state.keyword.trim().toLowerCase();
    var filtered = data.tasks.filter(function (task) {
      var matchesKeyword =
        !keyword ||
        task.orderNo.toLowerCase().includes(keyword) ||
        task.productSummary.toLowerCase().includes(keyword) ||
        task.specSummary.toLowerCase().includes(keyword);
      var matchesStatus = state.status === "all" || task.status === state.status;
      var matchesStart = !state.dueStart || task.contractShipDate >= state.dueStart;
      var matchesEnd = !state.dueEnd || task.contractShipDate <= state.dueEnd;
      return matchesKeyword && matchesStatus && matchesStart && matchesEnd;
    });

    return filtered.sort(function (a, b) {
      // Overdue + not completed → first
      var aUrgency = a.overdueDays > 0 && a.status !== "completed" ? 0 : a.status === "completed" ? 2 : 1;
      var bUrgency = b.overdueDays > 0 && b.status !== "completed" ? 0 : b.status === "completed" ? 2 : 1;
      if (aUrgency !== bUrgency) return aUrgency - bUrgency;
      return a.contractShipDate.localeCompare(b.contractShipDate);
    });
  }

  function renderTaskCard(task, index, icons, formatNumber) {
    var summaryHtml = escapeHtml(task.productSummary);

    return (
      '<article class="order-card" style="--card-index:' + index + '">' +
        '<div class="order-card__heading">' +
          '<div>' +
            '<p class="order-card__number">' + escapeHtml(task.orderNo) + '</p>' +
            '<h2>' + summaryHtml + '</h2>' +
          '</div>' +
          '<div class="order-card__badges">' +
            '<span class="status status--' + task.status + '">' + escapeHtml(task.statusLabel) + '</span>' +
            (task.overdueDays > 0 && task.status !== "completed" ? '<span class="overdue">逾期' + task.overdueDays + '天</span>' : "") +
          '</div>' +
        '</div>' +

        '<div class="order-card__due' + (task.overdueDays > 0 && task.status !== "completed" ? " order-card__due--overdue" : "") + '">' +
          '<span class="fact-icon">' + icons.calendar + '</span>' +
          '<span>合同出货时间</span>' +
          '<strong>' + escapeHtml(task.contractShipDateLabel) + '</strong>' +
        '</div>' +

        '<div class="order-card__progress">' +
          '<div class="progress-line">' +
            '<span>发货进度</span>' +
            '<div class="progress-track"><i style="width:' + task.progress + '%"></i></div>' +
            '<strong>' + task.progress + '%</strong>' +
          '</div>' +
          '<div class="quantity-line">' +
            '<span>已发 / 下单</span>' +
            '<strong>' + formatNumber(task.totalShipped) + ' / ' + formatNumber(task.totalAllocated) + '</strong>' +
          '</div>' +
          '<div class="quantity-line quantity-line--pending">' +
            '<span><strong class="pending-label">未发数量</strong></span>' +
            '<strong class="pending-value' + (task.totalPending > 0 ? " pending-value--warn" : "") + '">' + formatNumber(task.totalPending) + '</strong>' +
          '</div>' +
        '</div>' +

        '<button class="order-card__link" type="button" aria-label="查看任务 ' + escapeHtml(task.orderNo) + ' 详情" data-task-id="' + task.id + '">' +
          '<span>查看详情</span>' + icons.chevron +
        '</button>' +
      '</article>'
    );
  }

  function escapeHtml(str) {
    var div = document.createElement("div");
    div.appendChild(document.createTextNode(str));
    return div.innerHTML;
  }

  function formatNumber(n) {
    return n.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  }

  function mount(app) {
    var data = window.FactoryPrototypeData;
    var icons = window.FactoryIcons;
    var state = {
      keyword: "",
      status: "all",
      dueStart: "",
      dueEnd: "",
      filterOpen: false,
    };

    function render() {
      var visible = getVisibleTasks(data, state);
      var activeFilterCount = [
        state.status !== "all",
        Boolean(state.dueStart),
        Boolean(state.dueEnd),
      ].filter(Boolean).length;

      app.innerHTML =
        '<div class="page-shell">' +
          '<header class="page-header">' +
            '<div class="mini-titlebar">' +
              '<span class="titlebar-spacer" aria-hidden="true"></span>' +
              '<h1>任务</h1>' +
              '<div class="wechat-capsule" aria-hidden="true"><b>•••</b><i></i><span></span></div>' +
            '</div>' +
            '<div class="search-row">' +
              '<label class="search-box">' +
                icons.search +
                '<input id="task-search" type="search" value="' + escapeHtml(state.keyword) + '" placeholder="订单编号或产品名称" autocomplete="off" />' +
              '</label>' +
              '<button type="button" class="filter-button" id="open-filter">' +
                icons.filter + '<span>筛选</span>' + (activeFilterCount ? '<b>' + activeFilterCount + '</b>' : "") +
              '</button>' +
            '</div>' +
          '</header>' +

          '<section class="order-list" aria-label="任务列表">' +
            '<div class="result-summary"><span>共 ' + visible.length + ' 个任务</span></div>' +
            (visible.length
              ? visible.map(function (task, index) { return renderTaskCard(task, index, icons, formatNumber); }).join("")
              : '<div class="empty-state"><span>' + icons.search + '</span><h2>没有符合条件的任务</h2><p>可以调整搜索词或筛选条件后再试。</p><button id="clear-all" type="button">清除筛选</button></div>'
            ) +
            '<div class="create-shipment-bar">' +
              '<button type="button" class="primary-button create-shipment-btn" id="create-shipment-btn">创建发货单</button>' +
            '</div>' +
          '</section>' +

          '<nav class="tabbar" aria-label="工厂小程序一级导航">' +
            '<button type="button" class="tabbar__item is-active">' + icons.tasks + '<span>任务</span></button>' +
            '<button type="button" class="tabbar__item" data-prototype-target="发货记录">' + icons.truck + '<span>发货记录</span></button>' +
            '<button type="button" class="tabbar__item" data-prototype-target="我的">' + icons.profile + '<span>我的</span></button>' +
          '</nav>' +
        '</div>' +
        renderFilterSheet() +
        '<div class="prototype-toast" role="status"></div>';

      bindEvents();
    }

    function renderFilterSheet() {
      if (!state.filterOpen) return "";
      return (
        '<div class="sheet-layer" data-close-sheet>' +
          '<section class="filter-sheet" role="dialog" aria-modal="true" aria-labelledby="filter-title">' +
            '<div class="sheet-handle" aria-hidden="true"></div>' +
            '<header class="filter-sheet__header">' +
              '<div><p>工厂小程序</p><h2 id="filter-title">筛选任务</h2></div>' +
              '<button type="button" class="icon-button" data-close-sheet aria-label="关闭筛选">' + icons.close + '</button>' +
            '</header>' +
            '<div class="filter-sheet__body">' +
              '<label class="field">' +
                '<span>任务状态</span>' +
                '<select id="filter-status">' +
                  data.statusOptions.map(function (s) {
                    return '<option value="' + s[0] + '"' + (s[0] === state.status ? " selected" : "") + '>' + s[1] + '</option>';
                  }).join("") +
                '</select>' +
              '</label>' +
              '<fieldset class="field date-field">' +
                '<legend>合同出货时间范围</legend>' +
                '<div>' +
                  '<input id="filter-date-start" type="date" value="' + state.dueStart + '" aria-label="合同出货开始日期" />' +
                  '<span>至</span>' +
                  '<input id="filter-date-end" type="date" value="' + state.dueEnd + '" aria-label="合同出货结束日期" />' +
                '</div>' +
              '</fieldset>' +
            '</div>' +
            '<footer class="filter-sheet__actions">' +
              '<button type="button" class="secondary-button" id="reset-filter">重置</button>' +
              '<button type="button" class="primary-button" id="apply-filter">查看结果</button>' +
            '</footer>' +
          '</section>' +
        '</div>'
      );
    }

    function bindEvents() {
      document.querySelector("#task-search")?.addEventListener("input", function (event) {
        state.keyword = event.target.value;
        render();
        var input = document.querySelector("#task-search");
        input?.focus();
        input?.setSelectionRange(state.keyword.length, state.keyword.length);
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
        state.status = "all";
        state.dueStart = "";
        state.dueEnd = "";
        render();
      });

      document.querySelector("#apply-filter")?.addEventListener("click", function () {
        state.status = document.querySelector("#filter-status").value;
        state.dueStart = document.querySelector("#filter-date-start").value;
        state.dueEnd = document.querySelector("#filter-date-end").value;
        state.filterOpen = false;
        render();
      });

      document.querySelector("#clear-all")?.addEventListener("click", function () {
        state.keyword = "";
        state.status = "all";
        state.dueStart = "";
        state.dueEnd = "";
        render();
      });

      document.querySelector("#create-shipment-btn")?.addEventListener("click", function () {
        var page = window.FactoryPages["create-shipment"];
        if (page && page.mount) page.mount(app);
      });

      document.querySelectorAll("[data-task-id]").forEach(function (button) {
        button.addEventListener("click", function () {
          var taskId = button.dataset.taskId;
          var page = window.FactoryPages["task-detail"];
          if (page && page.mount) page.mount(app, taskId);
        });
      });

      document.querySelectorAll("[data-prototype-target]").forEach(function (button) {
        button.addEventListener("click", function () {
          showToast(button.dataset.prototypeTarget + "页面将在逐项确认后制作");
        });
      });
    }

    function showToast(msg) {
      var existing = document.querySelector(".prototype-toast");
      if (existing) {
        existing.textContent = msg;
        existing.classList.remove("is-visible");
        void existing.offsetWidth;
        existing.classList.add("is-visible");
        return;
      }
      var toast = document.createElement("div");
      toast.className = "prototype-toast";
      toast.textContent = msg;
      app.appendChild(toast);
      requestAnimationFrame(function () {
        toast.classList.add("is-visible");
        setTimeout(function () {
          toast.classList.remove("is-visible");
          setTimeout(function () { toast.remove(); }, 200);
        }, 1800);
      });
    }

    render();
  }

  window.FactoryPages ??= {};
  window.FactoryPages["task-list"] = { mount: mount };
})();