(function registerTaskDetail() {
  function getOrderDisplayStatus(task) {
    if (task.status === "completed") return { label: "已完成", tone: "completed" };
    if (task.overdueDays > 0) return { label: "已逾期", tone: "overdue" };
    return { label: "未完成", tone: "incomplete" };
  }

  function mount(app, taskId) {
    var data = window.FactoryPrototypeData;
    var icons = window.FactoryIcons;
    var task = data.tasks.find(function (t) { return t.id === taskId; }) || data.tasks[0];
    if (!task) return;
    var displayStatus = getOrderDisplayStatus(task);

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
                '<span class="status status--' + displayStatus.tone + '">' + displayStatus.label + '</span>' +
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
              '</div>' +
            '</div>' +
            '<div class="detail-quantity-grid">' +
              '<div><span>下单</span><strong>' + formatNumber(task.totalAllocated) + '</strong></div>' +
              '<div><span>已发</span><strong>' + formatNumber(task.totalShipped) + '</strong></div>' +
              '<div><span>未发</span><strong class="' + (task.totalPending > 0 ? "pending-warn" : "") + '">' + formatNumber(task.totalPending) + '</strong></div>' +
            '</div>' +
          '</section>' +

          '<section class="detail-section">' +
            '<header><h2>产品明细</h2><span>' + task.items.length + ' 条</span></header>' +
            '<div class="product-detail-list">' +
              '<div class="product-detail__head">' +
                '<span>序号</span><span>产品名称</span><span>颜色/规格</span><span>下单</span><span>已发</span><span>未发</span>' +
              '</div>' +
              task.items.map(function (item, idx) {
                return (
                  '<div class="product-detail-row">' +
                    '<span class="product-detail__index">' + (idx + 1) + '</span>' +
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
      '</div>';

    bindEvents();
  }

  function bindEvents() {
    document.querySelector("#back-to-tasks")?.addEventListener("click", function () {
      var app = document.getElementById("app");
      var page = window.FactoryPages["task-list"];
      if (page && page.mount) page.mount(app);
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

  window.FactoryPages ??= {};
  window.FactoryPages["task-detail"] = { mount: mount };
})();
