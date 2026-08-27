(function registerRepairDetail() {
  function escapeHtml(value) {
    var div = document.createElement("div");
    div.appendChild(document.createTextNode(value == null ? "" : String(value)));
    return div.innerHTML;
  }

  function formatNumber(value) {
    return Number(value || 0).toString().replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  }

  function groupByProduct(items) {
    return items.reduce(function (groups, item) {
      if (!groups[item.productName]) groups[item.productName] = [];
      groups[item.productName].push(item);
      return groups;
    }, {});
  }

  function getReturnTotals(task) {
    return task.returnBatches.reduce(function (totals, batch) {
      batch.lines.forEach(function (line) {
        totals.repaired += line.repaired;
        totals.scrapped += line.scrapped;
      });
      return totals;
    }, { repaired: 0, scrapped: 0 });
  }

  function renderProductGroups(task, icons) {
    var groups = groupByProduct(task.items);
    return Object.keys(groups).map(function (productName) {
      var items = groups[productName];
      var pendingTotal = items.reduce(function (sum, item) { return sum + item.pendingReturn; }, 0);
      return (
        '<details class="repair-product">' +
          '<summary>' +
            '<div><strong>' + escapeHtml(productName) + '</strong><span>' + items.length + ' 个规格</span></div>' +
            '<b>待返回 ' + formatNumber(pendingTotal) + '</b>' +
            '<i>' + icons.chevron + '</i>' +
          '</summary>' +
          '<div class="repair-spec-table">' +
            '<div class="repair-spec-table__head"><span>序号</span><span>颜色/规格</span><span>仓库退回数量</span><span>已返回数量</span><span>待返回数量</span></div>' +
            items.map(function (item, index) {
              return (
                '<div class="repair-spec-table__row">' +
                  '<span>' + (index + 1) + '</span>' +
                  '<strong>' + escapeHtml(item.spec) + '</strong>' +
                  '<span>' + formatNumber(item.warehouseReturned) + '</span>' +
                  '<span>' + formatNumber(item.returned) + '</span>' +
                  '<b class="' + (item.pendingReturn > 0 ? "pending-warn" : "") + '">' + formatNumber(item.pendingReturn) + '</b>' +
                '</div>'
              );
            }).join("") +
          '</div>' +
        '</details>'
      );
    }).join("");
  }

  function renderReturnHistory(task, icons) {
    if (!task.returnBatches.length) {
      return '<div class="repair-history-empty"><span>' + icons.truck + '</span><strong>尚未发回</strong><p>提交返修发回记录后将在这里显示。</p></div>';
    }
    return task.returnBatches.map(function (batch) {
      var total = batch.lines.reduce(function (sum, line) { return sum + line.repaired + line.scrapped; }, 0);
      return (
        '<details class="repair-history-batch">' +
          '<summary><div><strong>' + escapeHtml(batch.date) + '</strong><span>' + batch.lines.length + ' 个规格</span></div><b>发回 ' + formatNumber(total) + '</b><i>' + icons.chevron + '</i></summary>' +
          '<div class="repair-history-table">' +
            '<div class="repair-history-table__head"><span>产品名称</span><span>颜色/规格</span><span>返修数量</span><span>报废数量</span><span>本次发回</span></div>' +
            batch.lines.map(function (line) {
              return (
                '<div class="repair-history-table__row">' +
                  '<strong>' + escapeHtml(line.productName) + '</strong>' +
                  '<span>' + escapeHtml(line.spec) + '</span>' +
                  '<span>' + formatNumber(line.repaired) + '</span>' +
                  '<span>' + formatNumber(line.scrapped) + '</span>' +
                  '<b>' + formatNumber(line.repaired + line.scrapped) + '</b>' +
                '</div>'
              );
            }).join("") +
          '</div>' +
        '</details>'
      );
    }).join("");
  }

  function mount(app, repairId, backPage) {
    var data = window.FactoryPrototypeData;
    var icons = window.FactoryIcons;
    var task = data.repairTasks.find(function (item) { return item.id === repairId && !item.archived; });
    if (!task) {
      var listPage = window.FactoryPages["task-list"];
      if (listPage && listPage.mount) listPage.mount(app, "repair");
      return;
    }

    var totals = getReturnTotals(task);
    var hasAction = task.status !== "completed";

    app.innerHTML =
      '<div class="detail-page repair-detail-page' + (hasAction ? " repair-detail-page--action" : "") + '">' +
        '<header class="detail-titlebar">' +
          '<button type="button" class="back-button" id="repair-back" aria-label="返回">' + icons.back + '</button>' +
          '<h1>返修任务详情</h1>' +
          '<div class="wechat-capsule" aria-hidden="true"><b>•••</b><i></i><span></span></div>' +
        '</header>' +
        '<main class="repair-detail-content">' +
          '<section class="repair-summary-card">' +
            '<div class="repair-summary-card__heading"><div><span>返修单号</span><strong>' + escapeHtml(task.repairNo) + '</strong></div><em class="status status--' + (task.status === "completed" ? "completed" : "incomplete") + '">' + (task.status === "completed" ? "已完成" : "未完成") + '</em></div>' +
            '<div class="repair-summary-card__date"><span class="fact-icon">' + icons.calendar + '</span><span>退回日期</span><strong>' + escapeHtml(task.returnDateLabel) + '</strong></div>' +
            '<div class="repair-summary-card__progress">' +
              '<div><span>返回进度</span><strong>' + formatNumber(task.returned) + ' / ' + formatNumber(task.warehouseReturned) + '</strong><em>' + task.progress + '%</em></div>' +
              '<div class="progress-track"><i style="width:' + task.progress + '%"></i></div>' +
              '<p>待返回 <strong>' + formatNumber(task.pendingReturn) + '</strong> 件</p>' +
            '</div>' +
            '<div class="repair-summary-card__stats"><div><span>返修数量</span><strong>' + formatNumber(totals.repaired) + '</strong></div><div><span>报废数量</span><strong>' + formatNumber(totals.scrapped) + '</strong></div></div>' +
          '</section>' +
          '<section class="repair-detail-section">' +
            '<header><h2>质检附件</h2><span>原始质检文件</span></header>' +
            '<div class="repair-attachment">' +
              '<span class="repair-attachment__icon">' + icons.file + '</span>' +
              '<div><strong>' + escapeHtml(task.attachment.name) + '</strong><span>Excel · ' + escapeHtml(task.attachment.size) + '</span></div>' +
              '<button type="button" data-attachment-action="查看">查看</button><button type="button" data-attachment-action="下载">下载</button>' +
            '</div>' +
          '</section>' +
          '<section class="repair-detail-section">' +
            '<header><h2>待返回产品</h2><span>' + task.items.length + ' 个规格</span></header>' +
            '<div class="repair-product-list">' + renderProductGroups(task, icons) + '</div>' +
          '</section>' +
          '<section class="repair-detail-section">' +
            '<header><h2>历史发回记录</h2><span>' + task.returnBatches.length + ' 次</span></header>' +
            '<div class="repair-history-list">' + renderReturnHistory(task, icons) + '</div>' +
          '</section>' +
        '</main>' +
        (hasAction ? '<div class="repair-action-bar"><button type="button" class="primary-button" id="create-repair-return">发回返修品</button></div>' : "") +
      '</div>' +
      '<div class="prototype-toast" role="status"></div>';

    document.querySelector("#repair-back")?.addEventListener("click", function () {
      if (backPage === "notifications") {
        window.FactoryPages.notifications.mount(app, false);
        return;
      }
      var page = window.FactoryPages["task-list"];
      if (page && page.mount) page.mount(app, "repair");
    });

    document.querySelectorAll("[data-attachment-action]").forEach(function (button) {
      button.addEventListener("click", function () { showToast(button.dataset.attachmentAction + "质检附件（原型演示）"); });
    });

    document.querySelector("#create-repair-return")?.addEventListener("click", function () {
      var page = window.FactoryPages["repair-return"];
      if (page && page.mount) page.mount(app, task.id);
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

  window.FactoryPages ??= {};
  window.FactoryPages["repair-detail"] = { mount: mount };
})();
