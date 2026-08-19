(function registerRepairReturn() {
  var state = createInitialState();

  function createInitialState() {
    return {
      repairId: "",
      step: "edit",
      entries: {},
    };
  }

  function mount(app, repairId) {
    var task = findTask(repairId);
    if (!task || task.status === "completed") {
      return openRepairDetail(app, repairId);
    }

    state = createInitialState();
    state.repairId = repairId;
    task.items.forEach(function (item, index) {
      if (item.pendingReturn <= 0) return;
      state.entries[String(index)] = {
        selected: false,
        repaired: "",
        scrapped: "",
      };
    });
    render(app);
  }

  function render(app) {
    var task = findTask(state.repairId);
    if (!task || task.status === "completed") {
      return openRepairDetail(app, state.repairId);
    }

    var icons = window.FactoryIcons;
    app.innerHTML =
      '<div class="detail-page repair-return-page">' +
        '<header class="detail-titlebar">' +
          '<button type="button" class="back-button" id="repair-return-back" aria-label="返回">' + icons.back + '</button>' +
          '<h1>发回返修品</h1>' +
          '<div class="wechat-capsule" aria-hidden="true"><b>•••</b><i></i><span></span></div>' +
        '</header>' +
        renderStepIndicator() +
        '<main class="repair-return-content">' +
          renderSummary(task) +
          (state.step === "preview" ? renderPreview(task) : renderEditor(task)) +
        '</main>' +
      '</div>' +
      '<div class="prototype-toast" role="status"></div>';

    bindEvents(app, task);
  }

  function renderStepIndicator() {
    return (
      '<div class="repair-return-steps" data-step="' + state.step + '">' +
        '<div class="repair-return-step is-active"><span>' + (state.step === "preview" ? "✓" : "1") + '</span><strong>填写数量</strong></div>' +
        '<i></i>' +
        '<div class="repair-return-step' + (state.step === "preview" ? " is-active" : "") + '"><span>2</span><strong>预览提交</strong></div>' +
      '</div>'
    );
  }

  function renderSummary(task) {
    return (
      '<section class="repair-return-summary">' +
        '<div class="repair-return-summary__heading"><span>返修单号</span><strong>' + escapeHtml(task.repairNo) + '</strong></div>' +
        '<div class="repair-return-summary__progress">' +
          '<div><span>当前返回进度</span><strong>' + formatNumber(task.returned) + ' / ' + formatNumber(task.warehouseReturned) + '</strong><em>' + task.progress + '%</em></div>' +
          '<div class="progress-track"><i style="width:' + task.progress + '%"></i></div>' +
        '</div>' +
        '<div class="repair-return-summary__pending"><span>待返回总数量</span><strong>' + formatNumber(task.pendingReturn) + '</strong><small>件</small></div>' +
      '</section>'
    );
  }

  function renderEditor(task) {
    var groups = groupPendingItems(task);
    var groupHtml = Object.keys(groups).map(function (productName) {
      var rows = groups[productName];
      var productPending = rows.reduce(function (sum, row) { return sum + row.item.pendingReturn; }, 0);
      return (
        '<section class="repair-return-product">' +
          '<header><div><h2>' + escapeHtml(productName) + '</h2><span>' + rows.length + ' 个待返回规格</span></div><strong>待返回 ' + formatNumber(productPending) + '</strong></header>' +
          '<div class="repair-return-spec-list">' +
            rows.map(renderSpecEditor).join("") +
          '</div>' +
        '</section>'
      );
    }).join("");

    return (
      '<div class="repair-return-editor">' +
        '<div class="repair-return-hint">勾选本次发回的规格，并分别填写返修数量和报废数量。</div>' +
        groupHtml +
        renderLiveTotals() +
        '<button type="button" class="primary-button repair-return-primary" id="repair-return-preview">下一步：预览</button>' +
      '</div>'
    );
  }

  function renderSpecEditor(row) {
    var key = String(row.index);
    var entry = state.entries[key];
    var selectedClass = entry.selected ? " is-selected" : "";
    var disabled = entry.selected ? "" : " disabled";
    return (
      '<article class="repair-return-spec' + selectedClass + '">' +
        '<label class="repair-return-spec__select">' +
          '<input type="checkbox" data-return-select="' + key + '"' + (entry.selected ? " checked" : "") + ' />' +
          '<span><strong>' + escapeHtml(row.item.spec) + '</strong><small>选择本次发回</small></span>' +
        '</label>' +
        '<div class="repair-return-spec__facts">' +
          '<span>仓库退回 <b>' + formatNumber(row.item.warehouseReturned) + '</b></span>' +
          '<span>已返回 <b>' + formatNumber(row.item.returned) + '</b></span>' +
          '<span>待返回 <b>' + formatNumber(row.item.pendingReturn) + '</b></span>' +
        '</div>' +
        '<div class="repair-return-spec__inputs">' +
          '<label><span>返修数量</span><input type="number" inputmode="numeric" min="0" step="1" placeholder="0" data-return-repaired="' + key + '" value="' + escapeHtml(entry.repaired) + '"' + disabled + ' /></label>' +
          '<label><span>报废数量</span><input type="number" inputmode="numeric" min="0" step="1" placeholder="0" data-return-scrapped="' + key + '" value="' + escapeHtml(entry.scrapped) + '"' + disabled + ' /></label>' +
        '</div>' +
      '</article>'
    );
  }

  function renderLiveTotals() {
    var totals = getTotals();
    return (
      '<section class="repair-return-totals" aria-live="polite">' +
        '<div><span>本次返修</span><strong id="repair-return-total-repaired">' + formatNumber(totals.repaired) + '</strong></div>' +
        '<div><span>本次报废</span><strong id="repair-return-total-scrapped">' + formatNumber(totals.scrapped) + '</strong></div>' +
        '<div class="repair-return-totals__all"><span>本次返回总数量</span><strong id="repair-return-total-all">' + formatNumber(totals.total) + '</strong></div>' +
      '</section>'
    );
  }

  function renderPreview(task) {
    var lines = getSubmissionLines(task);
    var totals = getTotals();
    return (
      '<div class="repair-return-preview">' +
        '<section class="repair-return-preview__totals">' +
          '<div><span>返修数量</span><strong>' + formatNumber(totals.repaired) + '</strong></div>' +
          '<div><span>报废数量</span><strong>' + formatNumber(totals.scrapped) + '</strong></div>' +
          '<div><span>返回总数量</span><strong>' + formatNumber(totals.total) + '</strong></div>' +
        '</section>' +
        '<section class="repair-return-preview__list">' +
          '<header><h2>本次发回明细</h2><span>' + lines.length + ' 个规格</span></header>' +
          lines.map(function (line, index) {
            return (
              '<article>' +
                '<span class="repair-return-preview__index">' + (index + 1) + '</span>' +
                '<div><strong>' + escapeHtml(line.productName) + '</strong><span>' + escapeHtml(line.spec) + '</span></div>' +
                '<dl><div><dt>返修</dt><dd>' + formatNumber(line.repaired) + '</dd></div><div><dt>报废</dt><dd>' + formatNumber(line.scrapped) + '</dd></div><div><dt>返回</dt><dd>' + formatNumber(line.total) + '</dd></div></dl>' +
              '</article>'
            );
          }).join("") +
        '</section>' +
        '<div class="repair-return-actions">' +
          '<button type="button" class="secondary-button" id="repair-return-edit">返回修改</button>' +
          '<button type="button" class="primary-button" id="repair-return-submit">确认提交</button>' +
        '</div>' +
      '</div>'
    );
  }

  function bindEvents(app, task) {
    document.querySelector("#repair-return-back")?.addEventListener("click", function () {
      if (state.step === "preview") {
        state.step = "edit";
        render(app);
        return;
      }
      openRepairDetail(app, task.id);
    });

    document.querySelectorAll("[data-return-select]").forEach(function (checkbox) {
      checkbox.addEventListener("change", function () {
        var entry = state.entries[checkbox.dataset.returnSelect];
        entry.selected = checkbox.checked;
        if (!entry.selected) {
          entry.repaired = "";
          entry.scrapped = "";
        }
        render(app);
      });
    });

    document.querySelectorAll("[data-return-repaired]").forEach(function (input) {
      input.addEventListener("input", function () {
        state.entries[input.dataset.returnRepaired].repaired = input.value;
        updateLiveTotals();
      });
    });

    document.querySelectorAll("[data-return-scrapped]").forEach(function (input) {
      input.addEventListener("input", function () {
        state.entries[input.dataset.returnScrapped].scrapped = input.value;
        updateLiveTotals();
      });
    });

    document.querySelector("#repair-return-preview")?.addEventListener("click", function () {
      var validation = validateSubmission(task);
      if (!validation.ok) return showToast(validation.message);
      state.step = "preview";
      render(app);
    });

    document.querySelector("#repair-return-edit")?.addEventListener("click", function () {
      state.step = "edit";
      render(app);
    });

    document.querySelector("#repair-return-submit")?.addEventListener("click", function () {
      var validation = validateSubmission(task);
      if (!validation.ok) return showToast(validation.message);
      applySubmission(task);
      showToast("返修品发回记录已提交");
      setTimeout(function () { openRepairDetail(app, task.id); }, 900);
    });
  }

  function validateSubmission(task) {
    var selectedCount = 0;
    var itemIndexes = Object.keys(state.entries);

    for (var i = 0; i < itemIndexes.length; i += 1) {
      var key = itemIndexes[i];
      var entry = state.entries[key];
      if (!entry.selected) continue;
      selectedCount += 1;

      if (!isNonnegativeInteger(entry.repaired) || !isNonnegativeInteger(entry.scrapped)) {
        return { ok: false, message: "返修数量和报废数量只能填写非负整数" };
      }

      var repaired = parseQuantity(entry.repaired);
      var scrapped = parseQuantity(entry.scrapped);
      var item = task.items[Number(key)];
      if (repaired + scrapped === 0) {
        return { ok: false, message: item.spec + "的返修数量和报废数量不能同时为0" };
      }
      if (repaired + scrapped > item.pendingReturn) {
        return { ok: false, message: item.spec + "本次返回数量不能超过待返回数量" };
      }
    }

    if (selectedCount === 0) {
      return { ok: false, message: "请至少选择一个本次发回的产品规格" };
    }
    return { ok: true };
  }

  function applySubmission(task) {
    var lines = getSubmissionLines(task);
    task.returnBatches.push({
      id: buildBatchId(task),
      date: formatSubmittedDate(new Date()),
      lines: lines.map(function (line) {
        return {
          productName: line.productName,
          spec: line.spec,
          repaired: line.repaired,
          scrapped: line.scrapped,
        };
      }),
    });

    lines.forEach(function (line) {
      var item = task.items[line.itemIndex];
      item.returned += line.total;
      item.pendingReturn = Math.max(item.warehouseReturned - item.returned, 0);
    });

    task.returned = task.items.reduce(function (sum, item) { return sum + item.returned; }, 0);
    task.pendingReturn = Math.max(task.warehouseReturned - task.returned, 0);
    task.progress = task.warehouseReturned > 0 ? Math.round(task.returned / task.warehouseReturned * 100) : 100;
    task.status = task.pendingReturn === 0 ? "completed" : "processing";
    task.statusLabel = task.pendingReturn === 0 ? "已完成" : "未完成";
  }

  function getSubmissionLines(task) {
    return Object.keys(state.entries).filter(function (key) {
      return state.entries[key].selected;
    }).map(function (key) {
      var item = task.items[Number(key)];
      var entry = state.entries[key];
      var repaired = parseQuantity(entry.repaired);
      var scrapped = parseQuantity(entry.scrapped);
      return {
        itemIndex: Number(key),
        productName: item.productName,
        spec: item.spec,
        repaired: repaired,
        scrapped: scrapped,
        total: repaired + scrapped,
      };
    });
  }

  function groupPendingItems(task) {
    return task.items.reduce(function (groups, item, index) {
      if (item.pendingReturn <= 0) return groups;
      if (!groups[item.productName]) groups[item.productName] = [];
      groups[item.productName].push({ item: item, index: index });
      return groups;
    }, {});
  }

  function getTotals() {
    return Object.keys(state.entries).reduce(function (totals, key) {
      var entry = state.entries[key];
      if (!entry.selected) return totals;
      totals.repaired += parseQuantity(entry.repaired);
      totals.scrapped += parseQuantity(entry.scrapped);
      totals.total = totals.repaired + totals.scrapped;
      return totals;
    }, { repaired: 0, scrapped: 0, total: 0 });
  }

  function updateLiveTotals() {
    var totals = getTotals();
    setText("repair-return-total-repaired", formatNumber(totals.repaired));
    setText("repair-return-total-scrapped", formatNumber(totals.scrapped));
    setText("repair-return-total-all", formatNumber(totals.total));
  }

  function setText(id, value) {
    var node = document.getElementById(id);
    if (node) node.textContent = value;
  }

  function isNonnegativeInteger(value) {
    if (value === "") return true;
    return /^\d+$/.test(value);
  }

  function parseQuantity(value) {
    return /^\d+$/.test(value) ? Number(value) : 0;
  }

  function buildBatchId(task) {
    var now = new Date();
    var datePart = now.getFullYear() + pad2(now.getMonth() + 1) + pad2(now.getDate());
    return "return-" + datePart + "-" + String(task.returnBatches.length + 1).padStart(3, "0");
  }

  function formatSubmittedDate(date) {
    return date.getFullYear() + "年" + pad2(date.getMonth() + 1) + "月" + pad2(date.getDate()) + "日";
  }

  function pad2(value) {
    return String(value).padStart(2, "0");
  }

  function findTask(repairId) {
    return window.FactoryPrototypeData.repairTasks.find(function (task) {
      return task.id === repairId && !task.archived;
    });
  }

  function openRepairDetail(app, repairId) {
    var page = window.FactoryPages["repair-detail"];
    if (page && page.mount) page.mount(app, repairId);
  }

  function formatNumber(value) {
    return Number(value || 0).toString().replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  }

  function escapeHtml(value) {
    var div = document.createElement("div");
    div.appendChild(document.createTextNode(value == null ? "" : String(value)));
    return div.innerHTML;
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
  window.FactoryPages["repair-return"] = { mount: mount };
})();
