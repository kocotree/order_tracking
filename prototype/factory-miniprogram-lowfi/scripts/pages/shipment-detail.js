(function registerShipmentDetailPage() {
  function escapeHtml(value) {
    return String(value).replace(/[&<>'"]/g, function (char) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" }[char];
    });
  }

  function formatNumber(value) {
    return Number(value).toLocaleString("zh-CN");
  }

  function groupByOrder(lines) {
    return lines.reduce(function (groups, line) {
      (groups[line.orderNo] ??= []).push(line);
      return groups;
    }, {});
  }

  function total(lines) {
    return lines.reduce(function (sum, line) { return sum + line.quantity; }, 0);
  }

  function renderLineTable(lines, includeOrder) {
    return '<div class="shipment-detail-table' + (includeOrder ? ' shipment-detail-table--box' : '') + '">' +
      '<div class="shipment-detail-table__head"><span>序号</span><span>产品名称</span><span>颜色/规格</span><span>数量</span></div>' +
      lines.map(function (line, index) {
        return '<div class="shipment-detail-table__row"><span>' + (index + 1) + '</span><strong>' + escapeHtml(line.productName) + (includeOrder ? '　' + escapeHtml(line.orderNo) : '') + '</strong><span>' + escapeHtml(line.spec) + '</span><b>' + formatNumber(line.quantity) + '</b></div>';
      }).join("") + '</div>';
  }

  function mount(app, recordId, backPage) {
    var data = window.FactoryPrototypeData;
    var icons = window.FactoryIcons;
    var record = data.shipmentRecords.find(function (item) { return item.id === recordId; }) || data.shipmentRecords[0];
    var modalStep = "";
    var reason = "";

    function renderWithdrawSheet() {
      if (!modalStep) return "";
      var isConfirm = modalStep === "confirm";
      return '<div class="shipment-withdraw-layer" data-close-withdraw>' +
        '<section class="shipment-withdraw-sheet" role="dialog" aria-modal="true" aria-labelledby="withdraw-title">' +
          '<div class="sheet-handle" aria-hidden="true"></div>' +
          '<header><div><small>发货单 ' + escapeHtml(record.shipmentNo) + '</small><h2 id="withdraw-title">' + (isConfirm ? '确认撤回发货' : '撤回发货') + '</h2></div><button type="button" data-close-withdraw aria-label="关闭">' + icons.close + '</button></header>' +
          (isConfirm
            ? '<div class="withdraw-confirm"><p>提交后将进入管理员审核，审核通过前不会扣减订单已发数量。</p><dl><div><dt>发货日期</dt><dd>' + escapeHtml(record.shipDate) + '</dd></div><div><dt>发货数量</dt><dd>' + formatNumber(record.totalQuantity) + '</dd></div><div><dt>撤回原因</dt><dd>' + escapeHtml(reason) + '</dd></div></dl></div>'
            : '<div class="withdraw-form"><div class="withdraw-summary"><span><small>发货日期</small><strong>' + escapeHtml(record.shipDate) + '</strong></span><span><small>发货数量</small><strong>' + formatNumber(record.totalQuantity) + '</strong></span></div><label><span>撤回原因</span><textarea id="withdraw-reason" rows="4" maxlength="200" placeholder="请填写撤回原因">' + escapeHtml(reason) + '</textarea><small><b id="withdraw-count">' + reason.length + '</b>/200</small></label><p id="withdraw-error" role="alert"></p></div>') +
          '<footer><button type="button" class="secondary-button" id="withdraw-cancel">取消</button><button type="button" class="withdraw-submit" id="' + (isConfirm ? 'withdraw-confirm-submit' : 'withdraw-next') + '">' + (isConfirm ? '确认提交' : '提交撤回') + '</button></footer>' +
        '</section></div>';
    }

    function renderPage() {
      var orderGroups = groupByOrder(record.lines);
      var withdrawing = record.withdrawal && record.withdrawal.status === "processing";
      var operationCount = withdrawing ? 2 : 1;
      app.innerHTML = '<div class="detail-page shipment-detail-page">' +
        '<header class="detail-titlebar"><button type="button" class="back-button" id="shipment-detail-back" aria-label="返回">' + icons.back + '</button><h1>发货单详情</h1><div class="wechat-capsule" aria-hidden="true"><b>•••</b><i></i><span></span></div></header>' +
        '<main class="shipment-detail-content">' +
          '<section class="shipment-overview"><div class="shipment-overview__title"><h2>' + escapeHtml(record.shipmentNo) + '</h2>' + (withdrawing ? '<em>撤回处理中</em>' : '') + '</div><p><span>' + icons.calendar + '</span><small>发货日期</small><strong>' + escapeHtml(record.shipDate) + '</strong></p><div><span><small>发货数量</small><b>' + formatNumber(record.totalQuantity) + '</b></span><span><small>总箱数</small><b>' + formatNumber(record.totalBoxes) + '</b></span></div><footer><small>关联订单</small><b>' + escapeHtml(record.orderNos.join("、")) + '</b></footer></section>' +
          '<section class="shipment-detail-section"><header><h2>发货明细</h2><span>' + record.orderNos.length + ' 个订单</span></header><div>' +
            Object.keys(orderGroups).map(function (orderNo) { var lines = orderGroups[orderNo]; return '<details class="shipment-detail-group"><summary><span><strong>' + escapeHtml(orderNo) + '</strong><small>' + lines.length + ' 个产品规格</small></span><b>合计 ' + formatNumber(total(lines)) + '</b><i>' + icons.chevron + '</i></summary>' + renderLineTable(lines, false) + '</details>'; }).join("") + '</div></section>' +
          '<section class="shipment-detail-section"><header><h2>装箱明细</h2><span>' + record.boxes.length + ' 箱</span></header><div>' +
            record.boxes.map(function (box) { return '<details class="shipment-detail-group"><summary><span><strong>箱号 ' + escapeHtml(box.boxNo) + '</strong><small>' + box.lines.length + ' 个产品规格</small></span><b>合计 ' + formatNumber(total(box.lines)) + '</b><i>' + icons.chevron + '</i></summary>' + renderLineTable(box.lines, true) + '</details>'; }).join("") + '</div></section>' +
          '<section class="shipment-detail-section"><header><h2>发货凭证与备注</h2><span>' + record.proofs.length + ' 张凭证</span></header><div class="shipment-proof-list">' +
            (record.proofs.length ? record.proofs.map(function (proof, index) { return '<button type="button" data-proof="' + escapeHtml(proof) + '"><span>' + icons.camera + '</span><small>' + escapeHtml(proof) + '</small><b>' + (index + 1) + '</b></button>'; }).join("") : '<p class="shipment-empty-value">发货凭证　无</p>') +
            '<p class="shipment-note"><span>工厂备注</span><strong>' + escapeHtml(record.note || "无") + '</strong></p></div></section>' +
          '<section class="shipment-detail-section"><header><h2>操作记录</h2><span>' + operationCount + ' 条</span></header><div class="shipment-operation-list">' +
            (withdrawing ? '<div class="shipment-operation shipment-operation--withdraw"><i></i><div><strong>提交撤回发货</strong><p>' + escapeHtml(record.operator) + ' · ' + escapeHtml(record.withdrawal.submittedAt) + '</p><span>原因：' + escapeHtml(record.withdrawal.reason) + '</span></div></div>' : '') +
            '<div class="shipment-operation"><i></i><div><strong>提交发货单</strong><p>' + escapeHtml(record.operator) + ' · ' + escapeHtml(record.submittedAt) + '</p></div></div></div></section>' +
        '</main>' +
        '<div class="shipment-withdraw-bar"><button type="button" id="withdraw-shipment"' + (withdrawing ? ' disabled' : '') + '>' + (withdrawing ? '撤回处理中' : '撤回发货') + '</button></div>' +
        renderWithdrawSheet() + '<div class="prototype-toast" role="status"></div>' +
      '</div>';
      bindEvents();
    }

    function showToast(message) {
      var toast = document.querySelector(".prototype-toast");
      toast.textContent = message;
      toast.classList.remove("is-visible");
      void toast.offsetWidth;
      toast.classList.add("is-visible");
      setTimeout(function () { toast.classList.remove("is-visible"); }, 1800);
    }

    function bindEvents() {
      document.querySelector("#shipment-detail-back")?.addEventListener("click", function () {
        if (backPage === "notifications") {
          window.FactoryPages.notifications.mount(app, false);
          return;
        }
        window.FactoryPages["shipment-records"].mount(app);
      });
      document.querySelectorAll("[data-proof]").forEach(function (button) { button.addEventListener("click", function () { showToast(button.dataset.proof + " 大图预览"); }); });
      document.querySelector("#withdraw-shipment")?.addEventListener("click", function () { modalStep = "form"; renderPage(); });
      document.querySelector("#withdraw-reason")?.addEventListener("input", function (event) { reason = event.target.value; document.querySelector("#withdraw-count").textContent = reason.length; document.querySelector("#withdraw-error").textContent = ""; });
      document.querySelector(".shipment-withdraw-layer")?.addEventListener("click", function (event) {
        if (event.target !== event.currentTarget) return;
        modalStep = "";
        renderPage();
      });
      document.querySelector(".shipment-withdraw-sheet > header [data-close-withdraw]")?.addEventListener("click", function () { modalStep = ""; renderPage(); });
      document.querySelector("#withdraw-cancel")?.addEventListener("click", function () { modalStep = ""; renderPage(); });
      document.querySelector("#withdraw-next")?.addEventListener("click", function () {
        reason = document.querySelector("#withdraw-reason").value.trim();
        if (!reason) { document.querySelector("#withdraw-error").textContent = "请填写撤回原因"; return; }
        modalStep = "confirm"; renderPage();
      });
      document.querySelector("#withdraw-confirm-submit")?.addEventListener("click", function () {
        record.withdrawal = { status: "processing", reason: reason, submittedAt: "2026-08-19 11:20" };
        modalStep = "";
        renderPage();
        showToast("撤回申请已提交，等待管理员审核");
      });
    }

    renderPage();
  }

  window.FactoryPages ??= {};
  window.FactoryPages["shipment-detail"] = { mount: mount };
})();
