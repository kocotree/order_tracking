(function registerTaskList() {
  const render = function (container) {
    container.innerHTML = '<div class="page-shell" id="task-page"></div>';
    const shell = container.querySelector("#task-page");
    const data = window.FactoryPrototypeData;
    let tasks = [...data.tasks];
    let statusFilter = "all";
    let searchQuery = "";
    let dateRangeStart = "";
    let dateRangeEnd = "";

    const sortByPriority = function (list) {
      const now = new Date();
      list.sort(function (a, b) {
        var aIsOverdue = a.overdueDays > 0 ? 1 : 0;
        var bIsOverdue = b.overdueDays > 0 ? 1 : 0;
        if (aIsOverdue !== bIsOverdue) return bIsOverdue - aIsOverdue;
        var aDone = a.status === "completed" ? 1 : 0;
        var bDone = b.status === "completed" ? 1 : 0;
        if (aDone !== bDone) return aDone - bDone;
        return new Date(a.contractShipDate) - new Date(b.contractShipDate);
      });
      return list;
    };

    const applyFilters = function () {
      var list = tasks.filter(function (t) {
        if (statusFilter !== "all" && t.status !== statusFilter) return false;
        if (searchQuery) {
          var q = searchQuery.toLowerCase();
          if (
            t.orderNo.toLowerCase().indexOf(q) === -1 &&
            t.productName.toLowerCase().indexOf(q) === -1 &&
            t.spec.toLowerCase().indexOf(q) === -1
          ) return false;
        }
        if (dateRangeStart && t.contractShipDate < dateRangeStart) return false;
        if (dateRangeEnd && t.contractShipDate > dateRangeEnd) return false;
        return true;
      });
      return sortByPriority(list);
    };

    const renderFilterBar = function () {
      var el = document.createElement("div");
      el.className = "filter-bar";
      el.innerHTML =
        '<div class="filter-bar__row">' +
          '<div class="search-box" id="search-box">' +
            '<span class="search-box__icon">' + window.FactoryIcons.search + '</span>' +
            '<input type="text" class="search-box__input" id="search-input" placeholder="搜索订单编号或产品名称" value="' + window.FactoryShared.escapeHtml(searchQuery) + '" />' +
            (searchQuery ? '<button class="search-box__clear" id="search-clear">' + window.FactoryIcons.close + '</button>' : '') +
          '</div>' +
        '</div>' +
        '<div class="filter-bar__row filter-bar__row--second">' +
          '<select class="filter-select" id="status-select">' +
            data.statusOptions.map(function (s) {
              return '<option value="' + s[0] + '"' + (s[0] === statusFilter ? " selected" : "") + ">" + s[1] + "</option>";
            }).join("") +
          '</select>' +
          '<input type="date" class="filter-date" id="date-start" value="' + dateRangeStart + '" title="合同出货时间起" />' +
          '<span class="filter-date__sep">至</span>' +
          '<input type="date" class="filter-date" id="date-end" value="' + dateRangeEnd + '" title="合同出货时间止" />' +
        '</div>';
      return el;
    };

    const renderTaskCard = function (task) {
      var card = document.createElement("button");
      card.className = "task-card" + (task.overdueDays > 0 ? " task-card--overdue" : "");
      card.setAttribute("data-task-id", task.id);
      card.addEventListener("click", function () {
        window.FactoryShared.showToast("任务详情 — 后续逐页确认");
      });

      var statusBadge = "";
      if (task.overdueDays > 0) {
        statusBadge += '<span class="badge badge--overdue">逾期' + task.overdueDays + "天</span>";
      }
      statusBadge += '<span class="badge badge--' + task.status + '">' + task.statusLabel + "</span>";

      card.innerHTML =
        '<div class="task-card__head">' +
          '<div class="task-card__order">' +
            '<span class="task-card__order-no">' + window.FactoryShared.escapeHtml(task.orderNo) + '</span>' +
            (task.overdueDays > 0 ? '<span class="task-card__icon overdue-icon">' + window.FactoryIcons.overdue + "</span>" : "") +
          '</div>' +
          '<div class="task-card__badges">' + statusBadge + "</div>" +
        "</div>" +
        '<div class="task-card__product">' +
          '<span class="task-card__name">' + window.FactoryShared.escapeHtml(task.productName) + '</span>' +
          '<span class="task-card__spec">' + window.FactoryShared.escapeHtml(task.spec) + "</span>" +
        "</div>" +
        '<div class="task-card__meta">' +
          '<span class="task-card__due">合同出货：<em>' + task.contractShipDateLabel + "</em></span>" +
        "</div>" +
        '<div class="task-card__qty">' +
          '<div class="qty-item"><span class="qty-item__label">下单</span><span class="qty-item__value">' + task.allocated + "</span></div>" +
          '<div class="qty-item"><span class="qty-item__label">已发</span><span class="qty-item__value">' + task.shipped + "</span></div>" +
          '<div class="qty-item"><span class="qty-item__label">未发</span><span class="qty-item__value' + (task.pending > 0 ? " qty-item__value--warn" : "") + '">' + task.pending + "</span></div>" +
        "</div>" +
        '<div class="task-card__progress">' +
          '<div class="progress-track"><i style="width:' + task.progress + '%"></i></div>' +
        "</div>";
      return card;
    };

    const renderList = function () {
      var listEl = document.getElementById("task-list");
      if (!listEl) return;
      var filtered = applyFilters();
      listEl.innerHTML = "";
      if (filtered.length === 0) {
        listEl.innerHTML = '<div class="empty-state"><p>没有匹配的任务</p></div>';
        return;
      }
      filtered.forEach(function (t) {
        listEl.appendChild(renderTaskCard(t));
      });
    };

    const renderPage = function () {
      shell.innerHTML = "";

      // Header
      var header = document.createElement("header");
      header.className = "page-header";
      header.innerHTML =
        '<div class="mini-titlebar">' +
          '<div class="wechat-capsule"><b>…</b><i></i><span></span></div>' +
          "<h1>任务</h1>" +
          '<div style="width:88px"></div>' +
        "</div>";
      shell.appendChild(header);

      // Filter bar
      shell.appendChild(renderFilterBar());

      // Task count
      var countBar = document.createElement("div");
      countBar.className = "count-bar";
      var filtered = applyFilters();
      countBar.textContent = "共 " + filtered.length + " 个任务";
      shell.appendChild(countBar);

      // Task list
      var listContainer = document.createElement("div");
      listContainer.id = "task-list";
      listContainer.className = "task-list";
      shell.appendChild(listContainer);
      renderList();

      // Bottom nav
      var nav = document.createElement("nav");
      nav.className = "bottom-nav";
      nav.innerHTML =
        '<button class="nav-item nav-item--active" id="nav-tasks">' +
          '<span class="nav-item__icon">' + window.FactoryIcons.task + '</span>' +
          '<span class="nav-item__label">任务</span>' +
        "</button>" +
        '<button class="nav-item" id="nav-shipments">' +
          '<span class="nav-item__icon" id="nav-shipments-icon">' +
            '<svg viewBox="0 0 24 24"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>' +
          "</span>" +
          '<span class="nav-item__label">发货记录</span>' +
        "</button>" +
        '<button class="nav-item" id="nav-profile">' +
          '<span class="nav-item__icon">' +
            '<svg viewBox="0 0 24 24"><circle cx="12" cy="8" r="4"/><path d="M20 21a8 8 0 00-16 0"/></svg>' +
          "</span>" +
          '<span class="nav-item__label">我的</span>' +
        "</button>";

      // Nav events
      nav.querySelector("#nav-shipments").addEventListener("click", function () {
        window.FactoryShared.showToast("发货记录 — 后续逐页确认");
      });
      nav.querySelector("#nav-profile").addEventListener("click", function () {
        window.FactoryShared.showToast("我的 — 后续逐页确认");
      });

      shell.appendChild(nav);

      // Bind filter events
      var searchInput = document.getElementById("search-input");
      var statusSelect = document.getElementById("status-select");
      var dateStart = document.getElementById("date-start");
      var dateEnd = document.getElementById("date-end");
      var searchClear = document.getElementById("search-clear");

      var debounceTimer = null;
      var onFilterChange = function () {
        if (debounceTimer) clearTimeout(debounceTimer);
        debounceTimer = setTimeout(function () {
          searchQuery = searchInput.value.trim();
          statusFilter = statusSelect.value;
          dateRangeStart = dateStart.value;
          dateRangeEnd = dateEnd.value;
          renderPage();
        }, 150);
      };

      searchInput.addEventListener("input", onFilterChange);
      statusSelect.addEventListener("change", onFilterChange);
      dateStart.addEventListener("change", onFilterChange);
      dateEnd.addEventListener("change", onFilterChange);

      if (searchClear) {
        searchClear.addEventListener("click", function () {
          searchInput.value = "";
          searchQuery = "";
          renderPage();
        });
      }
    };

    renderPage();
  };

  window.FactoryShared = {
    escapeHtml: function (str) {
      var div = document.createElement("div");
      div.appendChild(document.createTextNode(str));
      return div.innerHTML;
    },
    showToast: function (msg) {
      var existing = document.querySelector(".prototype-toast");
      if (existing) existing.remove();
      var toast = document.createElement("div");
      toast.className = "prototype-toast";
      toast.textContent = msg;
      document.querySelector(".mini-program").appendChild(toast);
      requestAnimationFrame(function () {
        toast.classList.add("is-visible");
        setTimeout(function () {
          toast.classList.remove("is-visible");
          setTimeout(function () { toast.remove(); }, 200);
        }, 1800);
      });
    },
  };

  window.FactoryPages = window.FactoryPages || {};
  window.FactoryPages["task-list"] = { render: render };
})();