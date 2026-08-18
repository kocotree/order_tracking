(function registerTaskDetail() {
  function mount(app, taskId) {
    var data = window.FactoryPrototypeData;
    var icons = window.FactoryIcons;
    var task = data.tasks.find(function (t) { return t.id === taskId; }) || data.tasks[0];
    if (!task) return;

    var allDone = task.totalPending === 0;

    app.innerHTML =
      '<div class="detail-page">' +
        '<header class="detail-titlebar">' +
          '<button type="button" class="back-button" id="back-to-tasks" aria-label="返回任务列表">' + icons.back + '</button>' +
          '<h1>任务详情</h1>' +
          '<div class="wechat-capsule" aria-hidden="true"><b>•••</b><i></i><span></span></div>' +
        '</header>' +

        '<div class="detail-content" id="detail-content">' +
          '<section class="detail-summary-card">' +
            '<div class="order-card__heading">' +
              '<div><p class="order-card__number">' + escapeHtml(task.orderNo) + '</p><h2>' + escapeHtml(task.productSummary) + '</h2></div>' +
              '<div class="order-card__badges">' +
                '<span class="status status--' + task.status + '">' + escapeHtml(task.statusLabel) + '</span>' +
                (task.overdueDays > 0 && task.status !== "completed" ? '<span class="overdue">逾期' + task.overdueDays + '天</span>' : "") +
              '</div>' +
            '</div>' +

            '<p class="summary-due' + (task.overdueDays > 0 && task.status !== "completed" ? " summary-due--overdue" : "") + '">' +
              '<span class="fact-icon">' + icons.calendar + '</span>' +
              '<span>合同出货时间</span>' +
              '<strong>' + escapeHtml(task.contractShipDateLabel) + '</strong>' +
            '</p>' +

            '<div class="summary-progress">' +
              '<div>' +
                '<span>发货进度</span><div class="progress-track"><i style="width:' + task.progress + '%"></i></div><strong>' + task.progress + '%</strong>' +
                '<small>' + formatNumber(task.totalShipped) + ' / ' + formatNumber(task.totalAllocated) + '</small>' +
              '</div>' +
            '</div>' +
          '</section>' +

          '<section class="detail-section">' +
            '<header><h2>产品明细</h2><span>' + task.items.length + ' 条</span></header>' +
            '<div class="product-detail-list">' +
              '<div class="product-detail__head">' +
                '<span>产品名称</span><span>颜色/规格</span><span>下单</span><span>已发</span><span>未发</span>' +
              '</div>' +
              task.items.map(function (item, idx) {
                return (
                  '<div class="product-detail-row">' +
                    '<strong>' + escapeHtml(item.productName) + '</strong>' +
                    '<span>' + escapeHtml(item.spec) + '</span>' +
                    '<b>' + formatNumber(item.allocated) + '</b>' +
                    '<b>' + formatNumber(item.shipped) + '</b>' +
                    '<b class="' + (item.pending > 0 ? "pending-warn" : "") + '">' + formatNumber(item.pending) + '</b>' +
                  '</div>'
                );
              }).join("") +
            '</div>' +
          '</section>' +
        '</div>' +

        '<div class="detail-bottom-bar">' +
          '<div class="bottom-bar__summary">' +
            '<span>未发 <strong class="' + (!allDone ? "pending-warn" : "") + '">' + formatNumber(task.totalPending) + '</strong></span>' +
            '<span>已发 <strong>' + formatNumber(task.totalShipped) + '</strong> / 下单 ' + formatNumber(task.totalAllocated) + '</span>' +
          '</div>' +
          '<button type="button" class="primary-button bottom-bar__action" id="create-shipment"' + (allDone ? " disabled" : "") + '>' +
            '创建发货单' +
          '</button>' +
        '</div>' +
      '</div>' +
      '<div class="prototype-toast" role="status"></div>';

    bindEvents();
  }

  function bindEvents() {
    document.querySelector("#back-to-tasks")?.addEventListener("click", function () {
      var app = document.getElementById("app");
      var page = window.FactoryPages["task-list"];
      if (page && page.mount) page.mount(app);
    });

    document.querySelector("#create-shipment")?.addEventListener("click", function () {
      showToast("创建发货单 — 后续逐页确认");
    });
  }

  function escapeHtml(str) {
    var div = document.createElement("div");
    div.appendChild(document.createTextNode(str));
    return div.innerHTML;
  }

  function formatNumber(n) {
    return n.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  }

  function showToast(msg) {
    var app = document.getElementById("app");
    var existing = app.querySelector(".prototype-toast");
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

  window.FactoryPages ??= {};
  window.FactoryPages["task-detail"] = { mount: mount };
})();