(function registerCreateShipment() {
  var state = createInitialState();

  function createInitialState() {
    return {
      step: 1,
      containers: [],
      currentContainerId: "",
      boxCountInput: "",
      draftProduct: "",
      draftSpecKey: "",
      draftQty: "",
      photos: [],
      note: "",
      allocationOverrides: {},
    };
  }

  function mount(app) {
    state = createInitialState();
    render(app);
  }

  function render(app) {
    var icons = window.FactoryIcons;

    app.innerHTML =
      '<div class="detail-page ship-page">' +
        '<header class="detail-titlebar">' +
          '<button type="button" class="back-button" id="ship-back" aria-label="返回">' + icons.back + '</button>' +
          '<h1>创建发货单</h1>' +
          '<div class="wechat-capsule" aria-hidden="true"><b>•••</b><i></i><span></span></div>' +
        '</header>' +
        renderStepIndicator() +
        '<div class="detail-content ship-content" id="ship-content">' + renderStep() + '</div>' +
      '</div>' +
      '<div class="prototype-toast" role="status"></div>';

    bindEvents(app);
  }

  function renderStepIndicator() {
    var names = ["箱号", "装箱", "凭证", "提交"];
    return (
      '<div class="step-indicator" data-step="' + state.step + '">' +
        names.map(function (name, index) {
          var number = index + 1;
          var dotClass = number < state.step ? " step-dot--done" : (number === state.step ? " step-dot--active" : "");
          return (
            '<div class="step-group">' +
              '<div class="step-dot' + dotClass + '">' + (number < state.step ? "✓" : number) + '</div>' +
              '<span class="step-name' + (number === state.step ? " step-name--current" : "") + '">' + name + '</span>' +
            '</div>'
          );
        }).join("") +
      '</div>'
    );
  }

  function renderStep() {
    var icons = window.FactoryIcons;
    if (state.step === 1) return renderStep1(icons);
    if (state.step === 2) return renderStep2(icons);
    if (state.step === 3) return renderStep3(icons);
    if (state.step === 4) return renderStep4();
    return "";
  }

  function renderStep1(icons) {
    var boxPreviewHtml = state.containers.length
      ? '<div class="box-range-summary">' +
          '<span class="box-range-summary__icon">' + icons.box + '</span>' +
          '<div><strong>箱号 1–' + state.containers.length + '</strong><span>共 ' + state.containers.length + ' 箱，每箱分别填写装箱内容</span></div>' +
        '</div>' +
        '<div class="box-number-strip" aria-label="已生成箱号">' +
          state.containers.map(function (container) {
            return '<span>' + escapeHtml(container.boxNumbers[0]) + '</span>';
          }).join("") +
        '</div>'
      : '<div class="ship-empty"><span>' + icons.box + '</span><p>填写本次发货总箱数</p><small>系统将从箱号 1 开始自动排列</small></div>';

    return (
      '<section class="ship-section">' +
        '<header><h2>箱号</h2><span>共 ' + getTotalBoxCount() + ' 箱</span></header>' +
        '<div class="ship-section__body">' +
          '<div class="box-count-form">' +
            '<label class="field-label" for="box-count-input">本次发货总箱数</label>' +
            '<div class="box-add-row">' +
              '<input type="number" class="ship-input" id="box-count-input" inputmode="numeric" min="1" placeholder="填写总箱数" value="' + escapeHtml(state.boxCountInput) + '" />' +
              '<button type="button" class="primary-button compact-action" id="generate-boxes">生成箱号</button>' +
            '</div>' +
            '<p class="field-help">例如填写 6，系统自动生成箱号 1、2、3、4、5、6。</p>' +
          '</div>' +
          '<div class="box-preview">' + boxPreviewHtml + '</div>' +
        '</div>' +
      '</section>' +
      renderBottomBar(false, "下一步：装箱", "step-next", state.containers.length === 0)
    );
  }

  function renderStep2(icons) {
    ensurePackingSelection();
    var catalog = getCatalog();
    var container = getCurrentContainer();
    var productNames = getProductNames(catalog);
    var specs = catalog.filter(function (entry) { return entry.productName === state.draftProduct; });
    var selectedEntry = getCatalogEntry(state.draftSpecKey, catalog);
    var packedForSelected = selectedEntry ? getPackedQuantity(selectedEntry.key) : 0;
    var remainingForSelected = selectedEntry ? selectedEntry.totalPending - packedForSelected : 0;

    var productOptions = productNames.map(function (name) {
      return '<option value="' + escapeHtml(name) + '"' + (name === state.draftProduct ? " selected" : "") + '>' + escapeHtml(name) + '</option>';
    }).join("");

    var specOptions = specs.map(function (entry) {
      return '<option value="' + entry.key + '"' + (entry.key === state.draftSpecKey ? " selected" : "") + '>' + escapeHtml(entry.spec) + '</option>';
    }).join("");

    var detailHtml = container.items.length
      ? container.items.map(function (item) {
          var entry = getCatalogEntry(item.key, catalog);
          return (
            '<div class="packed-item">' +
              '<div class="packed-item__main">' +
                '<strong>' + escapeHtml(entry.productName) + '</strong>' +
                '<span>' + escapeHtml(entry.spec) + '</span>' +
              '</div>' +
              '<label class="packed-item__quantity">' +
                '<span>数量</span>' +
                '<input type="number" inputmode="numeric" min="1" class="ship-input packed-quantity-input" value="' + item.qty + '" data-packed-key="' + item.key + '" />' +
              '</label>' +
              '<button type="button" class="packed-item__remove" data-remove-packed="' + item.key + '" aria-label="删除该装箱明细">' + icons.close + '</button>' +
            '</div>'
          );
        }).join("")
      : '<div class="pack-empty">当前箱子还没有装箱明细</div>';

    var boxSwitcherHtml = state.containers.map(function (item) {
      var isCurrent = item.id === state.currentContainerId;
      var isPacked = item.items.length > 0;
      return (
        '<button type="button" class="box-switcher__item' + (isCurrent ? ' is-current' : '') + (isPacked ? ' is-packed' : '') + '" data-select-container="' + item.id + '">' +
          '<strong>' + escapeHtml(item.boxNumbers[0]) + '</strong>' +
          '<span>' + (isPacked ? getContainerPerBoxTotal(item) + '件' : '未装') + '</span>' +
        '</button>'
      );
    }).join("");

    return (
      '<section class="ship-section ship-section--selector">' +
        '<header><h2>当前装箱</h2><span>' + getPackedContainerCount() + ' / ' + state.containers.length + ' 已填写</span></header>' +
        '<div class="ship-section__body">' +
          '<label class="field-label">选择箱号</label>' +
          '<div class="box-switcher">' + boxSwitcherHtml + '</div>' +
          '<div class="current-pack-summary">' +
            '<div><span>箱号 ' + escapeHtml(container.boxNumbers[0]) + ' 已装</span><strong>' + formatNumber(getContainerPerBoxTotal(container)) + ' 件</strong></div>' +
          '</div>' +
        '</div>' +
      '</section>' +
      '<section class="ship-section">' +
        '<header><h2>添加产品规格</h2><span>不需要选择订单</span></header>' +
        '<div class="ship-section__body pack-form">' +
          '<label class="field-label" for="pack-product-select">产品名称</label>' +
          '<select class="ship-input ship-select" id="pack-product-select">' + productOptions + '</select>' +
          '<label class="field-label" for="pack-spec-select">颜色/规格</label>' +
          '<select class="ship-input ship-select" id="pack-spec-select">' + specOptions + '</select>' +
          '<div class="availability-line">' +
            '<span>总可发 <strong>' + formatNumber(selectedEntry ? selectedEntry.totalPending : 0) + '</strong></span>' +
            '<span>已装 <strong>' + formatNumber(packedForSelected) + '</strong></span>' +
            '<span>剩余 <strong class="availability-remaining">' + formatNumber(remainingForSelected) + '</strong></span>' +
          '</div>' +
          '<label class="field-label" for="pack-qty-input">装箱数量</label>' +
          '<div class="pack-quantity-row">' +
            '<input type="number" inputmode="numeric" min="1" class="ship-input" id="pack-qty-input" placeholder="填写数量" value="' + escapeHtml(state.draftQty) + '" />' +
            '<button type="button" class="primary-button compact-action" id="add-pack-item">添加明细</button>' +
          '</div>' +
        '</div>' +
      '</section>' +
      '<section class="ship-section">' +
        '<header><h2>' + escapeHtml(getContainerLabel(container)) + ' 明细</h2><span>' + container.items.length + ' 个规格</span></header>' +
        '<div class="ship-section__body packed-list">' + detailHtml + '</div>' +
      '</section>' +
      renderBottomBar(true, "下一步：凭证", "step-next2", false)
    );
  }

  function renderStep3(icons) {
    var photoHtml = state.photos.map(function (photo, index) {
      return (
        '<div class="photo-preview">' +
          '<img src="' + photo.url + '" alt="发货凭证 ' + (index + 1) + '" />' +
          '<button type="button" data-remove-photo="' + index + '" aria-label="删除照片">' + icons.close + '</button>' +
        '</div>'
      );
    }).join("");

    if (state.photos.length < 3) {
      photoHtml +=
        '<button type="button" class="photo-add" id="choose-photo">' +
          '<span>' + icons.camera + '</span><strong>添加照片</strong><small>' + state.photos.length + ' / 3</small>' +
        '</button>';
    }

    return (
      '<section class="ship-section">' +
        '<header><h2>发货凭证</h2><span>选填，最多 3 张</span></header>' +
        '<div class="ship-section__body">' +
          '<div class="photo-grid">' + photoHtml + '</div>' +
          '<input type="file" id="photo-input" accept="image/*" multiple hidden />' +
        '</div>' +
      '</section>' +
      '<section class="ship-section">' +
        '<header><h2>工厂备注</h2><span>选填</span></header>' +
        '<div class="ship-section__body">' +
          '<textarea class="ship-textarea" id="shipment-note" placeholder="填写物流或其他说明" rows="4">' + escapeHtml(state.note) + '</textarea>' +
        '</div>' +
      '</section>' +
      renderBottomBar(true, "下一步：预览", "step-next3", false)
    );
  }

  function renderStep4() {
    var catalog = getCatalog();
    var summaries = getShipmentSummaries(catalog);
    var packingHtml = state.containers.map(function (container) {
      return (
        '<div class="preview-container">' +
          '<div class="preview-container__head">' +
            '<div><strong>' + escapeHtml(getContainerLabel(container)) + '</strong><span>单箱装箱明细</span></div>' +
            '<b>' + formatNumber(getContainerTotal(container)) + ' 件</b>' +
          '</div>' +
          '<div class="preview-container__body">' +
            container.items.map(function (item, index) {
              var entry = getCatalogEntry(item.key, catalog);
              return (
                '<div class="preview-pack-row">' +
                  '<span class="preview-index">' + (index + 1) + '</span>' +
                  '<div><strong>' + escapeHtml(entry.productName) + '</strong><span>' + escapeHtml(entry.spec) + '</span></div>' +
                  '<b>' + formatNumber(item.qty) + ' 件</b>' +
                '</div>'
              );
            }).join("") +
          '</div>' +
        '</div>'
      );
    }).join("");

    var productHtml = summaries.map(function (summary, index) {
      var allocationHtml = "";
      if (summary.entry.sources.length > 1) {
        var allocation = getAllocation(summary.entry, summary.qty);
        allocationHtml =
          '<div class="allocation-block">' +
            '<div class="allocation-title"><strong>订单分配</strong><span>默认按合同出货时间从早到晚</span></div>' +
            summary.entry.sources.map(function (source) {
              return (
                '<label class="allocation-row">' +
                  '<span><strong>' + escapeHtml(source.orderNo) + '</strong><small>合同出货时间 ' + escapeHtml(source.contractShipDateLabel) + ' · 可分配 ' + formatNumber(source.pending) + '</small></span>' +
                  '<input type="number" inputmode="numeric" min="0" max="' + source.pending + '" class="ship-input allocation-input" value="' + (allocation[source.taskId] || 0) + '" data-allocation-spec="' + summary.entry.key + '" data-allocation-order="' + source.taskId + '" />' +
                '</label>'
              );
            }).join("") +
            '<div class="allocation-total">本规格应分配 <strong>' + formatNumber(summary.qty) + '</strong> 件</div>' +
          '</div>';
      }

      return (
        '<div class="preview-product">' +
          '<div class="preview-product__summary">' +
            '<span class="preview-index">' + (index + 1) + '</span>' +
            '<div><strong>' + escapeHtml(summary.entry.productName) + '</strong><span>' + escapeHtml(summary.entry.spec) + '</span></div>' +
            '<b>' + formatNumber(summary.qty) + ' 件</b>' +
          '</div>' +
          allocationHtml +
        '</div>'
      );
    }).join("");

    return (
      '<section class="preview-overview">' +
        '<div><span>总箱数</span><strong>' + formatNumber(getTotalBoxCount()) + '</strong></div>' +
        '<div><span>总数量</span><strong>' + formatNumber(getShipmentTotal()) + '</strong></div>' +
        '<div><span>产品规格</span><strong>' + summaries.length + '</strong></div>' +
      '</section>' +
      '<section class="ship-section">' +
        '<header><h2>产品规格汇总</h2><span>' + summaries.length + ' 个规格</span></header>' +
        '<div class="product-summary-list">' + productHtml + '</div>' +
      '</section>' +
      '<section class="ship-section">' +
        '<header><h2>装箱明细</h2><span>' + state.containers.length + ' 项</span></header>' +
        '<div class="preview-container-list">' + packingHtml + '</div>' +
      '</section>' +
      '<div class="submit-notice">提交后立即计入订单已发数量，不能直接编辑或删除；如需撤销，请从发货记录申请作废。</div>' +
      renderBottomBar(true, "提交发货单", "submit-shipment", false)
    );
  }

  function renderBottomBar(showPrevious, primaryText, primaryId, disabled) {
    return (
      '<div class="ship-bottom-bar">' +
        (showPrevious ? '<button type="button" class="secondary-button ship-bottom-bar__secondary" id="step-prev">上一步</button>' : '') +
        '<button type="button" class="primary-button ship-bottom-bar__primary" id="' + primaryId + '"' + (disabled ? " disabled" : "") + '>' + primaryText + '</button>' +
      '</div>'
    );
  }

  function bindEvents(app) {
    document.querySelector("#ship-back")?.addEventListener("click", function () {
      var page = window.FactoryPages["task-list"];
      if (page && page.mount) page.mount(app);
    });

    bindStep1Events(app);
    bindStep2Events(app);
    bindStep3Events(app);
    bindStep4Events(app);

    document.querySelector("#step-prev")?.addEventListener("click", function () {
      if (state.step > 1) {
        state.step -= 1;
        render(app);
      }
    });
  }

  function bindStep1Events(app) {
    document.querySelector("#box-count-input")?.addEventListener("input", function (event) {
      state.boxCountInput = event.target.value;
    });

    document.querySelector("#generate-boxes")?.addEventListener("click", function () {
      var boxCount = parsePositiveInteger(state.boxCountInput);
      if (!boxCount) return showToast("请填写大于 0 的总箱数");
      generateBoxes(boxCount);
      state.allocationOverrides = {};
      render(app);
    });

    document.querySelector("#step-next")?.addEventListener("click", function () {
      if (!state.containers.length) return;
      state.currentContainerId = state.currentContainerId || state.containers[0].id;
      state.step = 2;
      render(app);
    });
  }

  function bindStep2Events(app) {
    document.querySelectorAll("[data-select-container]").forEach(function (button) {
      button.addEventListener("click", function () {
        state.currentContainerId = button.dataset.selectContainer;
        state.draftQty = "";
        render(app);
      });
    });

    document.querySelector("#pack-product-select")?.addEventListener("change", function (event) {
      state.draftProduct = event.target.value;
      var firstSpec = getCatalog().find(function (entry) { return entry.productName === state.draftProduct; });
      state.draftSpecKey = firstSpec ? firstSpec.key : "";
      state.draftQty = "";
      render(app);
    });

    document.querySelector("#pack-spec-select")?.addEventListener("change", function (event) {
      state.draftSpecKey = event.target.value;
      state.draftQty = "";
      render(app);
    });

    document.querySelector("#pack-qty-input")?.addEventListener("input", function (event) {
      state.draftQty = event.target.value;
    });

    document.querySelector("#add-pack-item")?.addEventListener("click", function () {
      var container = getCurrentContainer();
      var entry = getCatalogEntry(state.draftSpecKey);
      var qty = parsePositiveInteger(state.draftQty);
      if (!entry || !qty) return showToast("请填写大于 0 的装箱数量");
      var existing = container.items.find(function (item) { return item.key === entry.key; });
      var nextPerBoxQty = (existing ? existing.qty : 0) + qty;
      if (!canSetPackedQuantity(container, entry, nextPerBoxQty)) return showToast("装箱数量超过该规格可发数量");
      if (existing) existing.qty = nextPerBoxQty;
      else container.items.push({ key: entry.key, qty: qty });
      state.draftQty = "";
      state.allocationOverrides = {};
      render(app);
    });

    document.querySelectorAll("[data-packed-key]").forEach(function (input) {
      input.addEventListener("change", function () {
        var container = getCurrentContainer();
        var entry = getCatalogEntry(input.dataset.packedKey);
        var item = container.items.find(function (packed) { return packed.key === input.dataset.packedKey; });
        var qty = parsePositiveInteger(input.value);
        if (!qty) {
          showToast("装箱数量必须大于 0");
          return render(app);
        }
        if (!canSetPackedQuantity(container, entry, qty)) {
          showToast("装箱数量超过该规格可发数量");
          return render(app);
        }
        item.qty = qty;
        state.allocationOverrides = {};
        render(app);
      });
    });

    document.querySelectorAll("[data-remove-packed]").forEach(function (button) {
      button.addEventListener("click", function () {
        var container = getCurrentContainer();
        container.items = container.items.filter(function (item) { return item.key !== button.dataset.removePacked; });
        state.allocationOverrides = {};
        render(app);
      });
    });

    document.querySelector("#step-next2")?.addEventListener("click", function () {
      var emptyContainer = state.containers.find(function (container) { return container.items.length === 0; });
      if (emptyContainer) return showToast("请先填写" + getContainerLabel(emptyContainer) + "的装箱明细");
      state.step = 3;
      render(app);
    });
  }

  function bindStep3Events(app) {
    document.querySelector("#choose-photo")?.addEventListener("click", function () {
      document.querySelector("#photo-input")?.click();
    });
    document.querySelector("#photo-input")?.addEventListener("change", function (event) {
      var remaining = 3 - state.photos.length;
      var files = Array.prototype.slice.call(event.target.files, 0, remaining);
      if (!files.length) return;
      var completed = 0;
      files.forEach(function (file) {
        var reader = new FileReader();
        reader.onload = function () {
          state.photos.push({ name: file.name, url: reader.result });
          completed += 1;
          if (completed === files.length) render(app);
        };
        reader.onerror = function () {
          completed += 1;
          if (completed === files.length) {
            showToast("部分照片读取失败");
            render(app);
          }
        };
        reader.readAsDataURL(file);
      });
    });
    document.querySelectorAll("[data-remove-photo]").forEach(function (button) {
      button.addEventListener("click", function () {
        state.photos.splice(parseInt(button.dataset.removePhoto, 10), 1);
        render(app);
      });
    });
    document.querySelector("#shipment-note")?.addEventListener("input", function (event) {
      state.note = event.target.value;
    });
    document.querySelector("#step-next3")?.addEventListener("click", function () {
      state.step = 4;
      render(app);
    });
  }

  function bindStep4Events(app) {
    document.querySelectorAll("[data-allocation-spec]").forEach(function (input) {
      input.addEventListener("input", function () {
        var key = input.dataset.allocationSpec;
        var entry = getCatalogEntry(key);
        var summary = getShipmentSummaries().find(function (item) { return item.entry.key === key; });
        if (!state.allocationOverrides[key]) state.allocationOverrides[key] = getAllocation(entry, summary.qty);
        state.allocationOverrides[key][input.dataset.allocationOrder] = parseNonNegativeInteger(input.value);
      });
    });

    document.querySelector("#submit-shipment")?.addEventListener("click", function () {
      var allocationError = validateAllocations();
      if (allocationError) return showToast(allocationError);
      showToast("发货单已提交");
      setTimeout(function () {
        var page = window.FactoryPages["task-list"];
        if (page && page.mount) page.mount(app);
      }, 1200);
    });
  }

  function getCatalog() {
    var grouped = {};
    window.FactoryPrototypeData.tasks.forEach(function (task) {
      if (task.status === "completed") return;
      task.items.forEach(function (item) {
        if (item.pending <= 0) return;
        var key = makeSpecKey(item.productName, item.spec);
        if (!grouped[key]) {
          grouped[key] = {
            key: key,
            productName: item.productName,
            spec: item.spec,
            totalPending: 0,
            firstDate: task.contractShipDate,
            sources: [],
          };
        }
        grouped[key].totalPending += item.pending;
        grouped[key].sources.push({
          taskId: task.id,
          orderNo: task.orderNo,
          contractShipDate: task.contractShipDate,
          contractShipDateLabel: task.contractShipDateLabel,
          pending: item.pending,
        });
        if (task.contractShipDate < grouped[key].firstDate) grouped[key].firstDate = task.contractShipDate;
      });
    });

    return Object.keys(grouped).map(function (key) {
      grouped[key].sources.sort(function (a, b) { return a.contractShipDate.localeCompare(b.contractShipDate); });
      return grouped[key];
    }).sort(function (a, b) {
      return a.firstDate.localeCompare(b.firstDate) || a.productName.localeCompare(b.productName, "zh-CN");
    });
  }

  function getProductNames(catalog) {
    var names = [];
    catalog.forEach(function (entry) {
      if (names.indexOf(entry.productName) === -1) names.push(entry.productName);
    });
    return names;
  }

  function ensurePackingSelection() {
    var catalog = getCatalog();
    if (!state.currentContainerId && state.containers.length) state.currentContainerId = state.containers[0].id;
    if (!state.draftProduct && catalog.length) state.draftProduct = catalog[0].productName;
    var matchingSpecs = catalog.filter(function (entry) { return entry.productName === state.draftProduct; });
    if (!matchingSpecs.some(function (entry) { return entry.key === state.draftSpecKey; })) {
      state.draftSpecKey = matchingSpecs[0]?.key || "";
    }
  }

  function generateBoxes(boxCount) {
    var existingById = {};
    state.containers.forEach(function (container) { existingById[container.id] = container; });
    state.containers = [];
    for (var number = 1; number <= boxCount; number += 1) {
      var id = "box-" + number;
      var existing = existingById[id];
      state.containers.push(existing || { id: id, type: "single", boxNumbers: [String(number)], items: [] });
    }
    if (!state.containers.some(function (container) { return container.id === state.currentContainerId; })) {
      state.currentContainerId = state.containers[0].id;
    }
  }

  function getCurrentContainer() {
    return state.containers.find(function (container) { return container.id === state.currentContainerId; }) || state.containers[0];
  }

  function getContainerLabel(container) {
    return "箱号 " + container.boxNumbers[0];
  }

  function getTotalBoxCount() {
    return state.containers.length;
  }

  function getPackedContainerCount() {
    return state.containers.filter(function (container) { return container.items.length > 0; }).length;
  }

  function getContainerPerBoxTotal(container) {
    return container.items.reduce(function (sum, item) { return sum + item.qty; }, 0);
  }

  function getContainerTotal(container) {
    return getContainerPerBoxTotal(container);
  }

  function getShipmentTotal() {
    return state.containers.reduce(function (sum, container) { return sum + getContainerTotal(container); }, 0);
  }

  function getPackedQuantity(key, excludedContainerId) {
    return state.containers.reduce(function (sum, container) {
      if (container.id === excludedContainerId) return sum;
      var item = container.items.find(function (packed) { return packed.key === key; });
      return sum + (item ? item.qty : 0);
    }, 0);
  }

  function canSetPackedQuantity(container, entry, perBoxQty) {
    return getPackedQuantity(entry.key, container.id) + perBoxQty <= entry.totalPending;
  }

  function getShipmentSummaries(catalog) {
    catalog = catalog || getCatalog();
    var quantities = {};
    state.containers.forEach(function (container) {
      container.items.forEach(function (item) {
        quantities[item.key] = (quantities[item.key] || 0) + item.qty;
      });
    });
    return catalog.filter(function (entry) { return quantities[entry.key] > 0; }).map(function (entry) {
      return { entry: entry, qty: quantities[entry.key] };
    });
  }

  function getAllocation(entry, totalQty) {
    if (state.allocationOverrides[entry.key]) return state.allocationOverrides[entry.key];
    var remaining = totalQty;
    var allocation = {};
    entry.sources.forEach(function (source) {
      var qty = Math.min(source.pending, remaining);
      allocation[source.taskId] = qty;
      remaining -= qty;
    });
    return allocation;
  }

  function validateAllocations() {
    var summaries = getShipmentSummaries();
    for (var i = 0; i < summaries.length; i += 1) {
      var summary = summaries[i];
      if (summary.entry.sources.length < 2) continue;
      var allocation = getAllocation(summary.entry, summary.qty);
      var total = 0;
      for (var j = 0; j < summary.entry.sources.length; j += 1) {
        var source = summary.entry.sources[j];
        var qty = parseNonNegativeInteger(allocation[source.taskId]);
        if (qty > source.pending) return source.orderNo + "的分配数量超过可发数量";
        total += qty;
      }
      if (total !== summary.qty) return summary.entry.spec + "的订单分配合计应为 " + summary.qty + " 件";
    }
    return "";
  }

  function getCatalogEntry(key, catalog) {
    return (catalog || getCatalog()).find(function (entry) { return entry.key === key; });
  }

  function makeSpecKey(productName, spec) {
    return encodeURIComponent(productName + "\u0001" + spec);
  }

  function parsePositiveInteger(value) {
    var number = Number(value);
    return Number.isInteger(number) && number > 0 ? number : 0;
  }

  function parseNonNegativeInteger(value) {
    var number = Number(value);
    return Number.isInteger(number) && number >= 0 ? number : 0;
  }

  function escapeHtml(value) {
    var div = document.createElement("div");
    div.appendChild(document.createTextNode(value == null ? "" : String(value)));
    return div.innerHTML;
  }

  function formatNumber(value) {
    return Number(value || 0).toString().replace(/\B(?=(\d{3})+(?!\d))/g, ",");
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
  window.FactoryPages["create-shipment"] = { mount: mount };
})();
