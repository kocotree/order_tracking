(function registerCreateShipment() {
  var state = {
    step: 1,
    boxes: [],
    boxGroupStart: "",
    boxGroupEnd: "",
    singleBox: "",
    editingBoxIndex: null,
  };

  function mount(app) {
    state.step = 1;
    state.boxes = [];
    state.boxGroupStart = "";
    state.boxGroupEnd = "";
    state.singleBox = "";
    state.editingBoxIndex = null;
    render(app);
  }

  function render(app) {
    var data = window.FactoryPrototypeData;
    var icons = window.FactoryIcons;

    app.innerHTML =
      '<div class="detail-page ship-page">' +
        '<header class="detail-titlebar">' +
          '<button type="button" class="back-button" id="ship-back" aria-label="返回">' + icons.back + '</button>' +
          '<h1>创建发货单</h1>' +
          '<div class="wechat-capsule" aria-hidden="true"><b>•••</b><i></i><span></span></div>' +
        '</header>' +

        '<div class="step-indicator' + (state.step > 1 ? ' step-indicator--progress' : '') + '" style="--progress: ' + ((state.step - 1) / 3 * 100) + '%">' +
          '<div class="step-group">' +
            '<div class="step-dot step-dot--active">1</div>' +
            '<span class="step-name step-name--current">箱号</span>' +
          '</div>' +
          '<div class="step-group">' +
            '<div class="step-dot' + (state.step >= 2 ? ' step-dot--active' : '') + '">2</div>' +
            '<span class="step-name' + (state.step === 2 ? ' step-name--current' : '') + '">装箱</span>' +
          '</div>' +
          '<div class="step-group">' +
            '<div class="step-dot' + (state.step >= 3 ? ' step-dot--active' : '') + '">3</div>' +
            '<span class="step-name' + (state.step === 3 ? ' step-name--current' : '') + '">凭证</span>' +
          '</div>' +
          '<div class="step-group">' +
            '<div class="step-dot' + (state.step >= 4 ? ' step-dot--active' : '') + '">4</div>' +
            '<span class="step-name' + (state.step === 4 ? ' step-name--current' : '') + '">提交</span>' +
          '</div>' +
        '</div>' +

        '<div class="detail-content" id="ship-content">' +
          renderStep() +
        '</div>' +
      '</div>' +
      '<div class="prototype-toast" role="status"></div>';

    bindEvents(app);
  }

  function renderStep() {
    var icons = window.FactoryIcons;
    switch (state.step) {
      case 1: return renderStep1(icons);
      case 2: return renderStep2(icons);
      case 3: return renderStep3(icons);
      case 4: return renderStep4(icons);
      default: return "";
    }
  }

  function renderStep1(icons) {
    var boxListHtml = state.boxes.length
      ? state.boxes.map(function (b, i) {
          return (
            '<div class="box-item">' +
              '<span class="box-item__icon">' + icons.box + '</span>' +
              '<span class="box-item__label">箱号 ' + escapeHtml(b) + '</span>' +
              '<button class="box-item__remove" data-remove-box="' + i + '">' + icons.close + '</button>' +
            '</div>'
          );
        }).join("")
      : '<p class="detail-empty">暂无箱号，请在下方添加</p>';

    return (
      '<section class="ship-section">' +
        '<header><h2>添加箱号</h2></header>' +
        '<div class="ship-section__body">' +
          '<div class="box-list">' + boxListHtml + '</div>' +

          '<div class="box-add-group">' +
            '<label class="box-add-group__label">单个添加</label>' +
            '<div class="box-add-group__row">' +
              '<input type="text" class="ship-input" id="single-box-input" placeholder="输入箱号" value="' + escapeHtml(state.singleBox) + '" />' +
              '<button type="button" class="primary-button box-add-btn" id="add-single-box">添加</button>' +
            '</div>' +
          '</div>' +

          '<div class="box-add-group">' +
            '<label class="box-add-group__label">装箱组批量</label>' +
            '<div class="box-add-group__row">' +
              '<input type="text" class="ship-input" id="group-start-input" placeholder="起始箱号" value="' + escapeHtml(state.boxGroupStart) + '" />' +
              '<span class="box-add-group__sep">至</span>' +
              '<input type="text" class="ship-input" id="group-end-input" placeholder="结束箱号" value="' + escapeHtml(state.boxGroupEnd) + '" />' +
              '<button type="button" class="primary-button box-add-btn" id="add-box-group">批量</button>' +
            '</div>' +
          '</div>' +
        '</div>' +
      '</section>' +
      '<div class="ship-bottom-bar">' +
        '<button type="button" class="primary-button ship-bottom-bar__action" id="step-next"' + (state.boxes.length === 0 ? ' disabled' : '') + '>下一步：装箱</button>' +
      '</div>'
    );
  }

  function renderStep2(icons) {
    var data = window.FactoryPrototypeData;
    // Collect all unfinished tasks as available order items
    var availableItems = [];
    data.tasks.forEach(function (task) {
      if (task.status === "completed") return;
      task.items.forEach(function (item) {
        if (item.pending > 0) {
          availableItems.push({
            orderNo: task.orderNo,
            productName: item.productName,
            spec: item.spec,
            pending: item.pending,
            contractShipDate: task.contractShipDate,
          });
        }
      });
    });

    // Sort by contract ship date
    availableItems.sort(function (a, b) {
      return a.contractShipDate.localeCompare(b.contractShipDate);
    });

    var boxSelectHtml = state.boxes.map(function (b, i) {
      return '<option value="' + i + '">箱号 ' + escapeHtml(b) + '</option>';
    }).join("");

    var itemRowsHtml = availableItems.map(function (item) {
      return (
        '<div class="pack-item-row">' +
          '<div class="pack-item-row__info">' +
            '<strong>' + escapeHtml(item.orderNo) + '</strong>' +
            '<span>' + escapeHtml(item.productName) + ' · ' + escapeHtml(item.spec) + '</span>' +
          '</div>' +
          '<div class="pack-item-row__qty">' +
            '<span class="pack-item-row__pending">可发 ' + formatNumber(item.pending) + '</span>' +
            '<input type="number" class="ship-input pack-item-row__input" min="0" max="' + item.pending + '" value="0" data-item-key="' + escapeHtml(item.orderNo) + '|' + escapeHtml(item.productName) + '|' + escapeHtml(item.spec) + '" />' +
          '</div>' +
        '</div>'
      );
    }).join("");

    return (
      '<section class="ship-section">' +
        '<header><h2>选择箱子</h2></header>' +
        '<div class="ship-section__body">' +
          '<label class="field-label">当前箱号</label>' +
          '<select class="ship-input" id="box-select">' + boxSelectHtml + '</select>' +
        '</div>' +
      '</section>' +

      '<section class="ship-section">' +
        '<header><h2>装箱内容</h2><span>按合同出货时间优先</span></header>' +
        '<div class="ship-section__body">' +
          itemRowsHtml.length
            ? itemRowsHtml
            : '<p class="detail-empty">没有可发货的任务</p>' +
        '</div>' +
      '</section>' +

      '<div class="ship-bottom-bar">' +
        '<button type="button" class="secondary-button ship-bottom-bar__action" id="step-prev">上一步</button>' +
        '<button type="button" class="primary-button ship-bottom-bar__action" id="step-next2">下一步：凭证</button>' +
      '</div>'
    );
  }

  function renderStep3(icons) {
    return (
      '<section class="ship-section">' +
        '<header><h2>发货凭证与备注</h2></header>' +
        '<div class="ship-section__body">' +
          '<div class="photo-upload-area">' +
            '<label class="field-label">凭证照片（选填，最多3张）</label>' +
            '<div class="photo-grid">' +
              '<div class="photo-placeholder">' +
                '<span class="photo-placeholder__icon">' + icons.camera + '</span>' +
                '<span class="photo-placeholder__text">添加照片</span>' +
              '</div>' +
              '<div class="photo-placeholder">' +
                '<span class="photo-placeholder__icon">' + icons.camera + '</span>' +
                '<span class="photo-placeholder__text">添加照片</span>' +
              '</div>' +
              '<div class="photo-placeholder">' +
                '<span class="photo-placeholder__icon">' + icons.camera + '</span>' +
                '<span class="photo-placeholder__text">添加照片</span>' +
              '</div>' +
            '</div>' +
          '</div>' +
          '<div class="note-area">' +
            '<label class="field-label">备注（选填）</label>' +
            '<textarea class="ship-textarea" placeholder="输入备注内容，如物流信息等" rows="3"></textarea>' +
          '</div>' +
        '</div>' +
      '</section>' +

      '<div class="ship-bottom-bar">' +
        '<button type="button" class="secondary-button ship-bottom-bar__action" id="step-prev">上一步</button>' +
        '<button type="button" class="primary-button ship-bottom-bar__action" id="step-next3">下一步：预览</button>' +
      '</div>'
    );
  }

  function renderStep4(icons) {
    var data = window.FactoryPrototypeData;
    var totalBoxes = state.boxes.length;
    var totalQty = 0;
    data.tasks.forEach(function (task) {
      if (task.status === "completed") return;
      task.items.forEach(function (item) {
        var key = escapeHtml(task.orderNo) + '|' + escapeHtml(item.productName) + '|' + escapeHtml(item.spec);
        var input = document.querySelector('[data-item-key="' + key.replace(/"/g, '&quot;') + '"]');
        if (input) totalQty += parseInt(input.value) || 0;
      });
    });

    return (
      '<section class="ship-section">' +
        '<header><h2>预览并提交</h2></header>' +
        '<div class="ship-section__body">' +
          '<div class="preview-summary">' +
            '<div class="preview-summary__item"><span>总箱数</span><strong>' + totalBoxes + '</strong></div>' +
            '<div class="preview-summary__item"><span>总数量</span><strong>' + formatNumber(totalQty) + '</strong></div>' +
          '</div>' +
          '<div class="preview-box-list">' +
            state.boxes.map(function (b) {
              return (
                '<div class="preview-box-item">' +
                  '<div class="preview-box-item__head">箱号 ' + escapeHtml(b) + '</div>' +
                  '<div class="preview-box-item__body">（装箱明细待确认）</div>' +
                '</div>'
              );
            }).join("") +
          '</div>' +
        '</div>' +
      '</section>' +

      '<div class="ship-bottom-bar">' +
        '<button type="button" class="secondary-button ship-bottom-bar__action" id="step-prev">上一步</button>' +
        '<button type="button" class="primary-button ship-bottom-bar__action" id="submit-shipment">提交发货单</button>' +
      '</div>'
    );
  }

  function bindEvents(app) {
    document.querySelector("#ship-back")?.addEventListener("click", function () {
      var page = window.FactoryPages["task-list"];
      if (page && page.mount) page.mount(app);
    });

    // Step 1 events
    document.querySelector("#add-single-box")?.addEventListener("click", function () {
      var input = document.querySelector("#single-box-input");
      var val = input.value.trim();
      if (val && state.boxes.indexOf(val) === -1) {
        state.boxes.push(val);
        state.singleBox = "";
        render(app);
      }
    });

    document.querySelector("#add-box-group")?.addEventListener("click", function () {
      var start = document.querySelector("#group-start-input").value.trim();
      var end = document.querySelector("#group-end-input").value.trim();
      if (start && end) {
        // Simple numeric range
        var startNum = parseInt(start);
        var endNum = parseInt(end);
        if (!isNaN(startNum) && !isNaN(endNum) && startNum <= endNum) {
          for (var i = startNum; i <= endNum; i++) {
            var boxNum = i.toString();
            if (state.boxes.indexOf(boxNum) === -1) {
              state.boxes.push(boxNum);
            }
          }
          state.boxGroupStart = "";
          state.boxGroupEnd = "";
          render(app);
        }
      }
    });

    document.querySelectorAll("[data-remove-box]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var idx = parseInt(btn.dataset.removeBox);
        if (!isNaN(idx) && idx >= 0 && idx < state.boxes.length) {
          state.boxes.splice(idx, 1);
          render(app);
        }
      });
    });

    document.querySelector("#step-next")?.addEventListener("click", function () {
      if (state.boxes.length > 0) {
        state.step = 2;
        render(app);
      }
    });

    // Step 2 events
    document.querySelector("#step-next2")?.addEventListener("click", function () {
      state.step = 3;
      render(app);
    });

    // Step 3 events
    document.querySelector("#step-next3")?.addEventListener("click", function () {
      state.step = 4;
      render(app);
    });

    // Step common events
    document.querySelectorAll("#step-prev").forEach(function (btn) {
      btn.addEventListener("click", function () {
        if (state.step > 1) {
          state.step--;
          render(app);
        }
      });
    });

    document.querySelector("#submit-shipment")?.addEventListener("click", function () {
      showToast("发货单已提交！");
      // After a moment, go back to task list
      setTimeout(function () {
        var page = window.FactoryPages["task-list"];
        if (page && page.mount) page.mount(app);
      }, 1500);
    });

    // Real-time input sync
    document.querySelector("#single-box-input")?.addEventListener("input", function (e) {
      state.singleBox = e.target.value;
    });
    document.querySelector("#group-start-input")?.addEventListener("input", function (e) {
      state.boxGroupStart = e.target.value;
    });
    document.querySelector("#group-end-input")?.addEventListener("input", function (e) {
      state.boxGroupEnd = e.target.value;
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
  window.FactoryPages["create-shipment"] = { mount: mount };
})();