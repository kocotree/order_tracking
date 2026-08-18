(function registerRepairDetailPage() {
  function groupByProduct(lines) {
    return lines.reduce((groups, line) => {
      groups[line.productName] ??= [];
      groups[line.productName].push(line);
      return groups;
    }, {});
  }

  function renderQualityGroups(detail, state, icons, formatNumber) {
    const groups = groupByProduct(detail.qualityLines);
    return Object.entries(groups)
      .map(([productName, lines]) => {
        const expanded = state.expandedRepairProducts.includes(productName);
        const total = lines.reduce((sum, line) => sum + line.warehouseReturnQuantity, 0);
        return `
          <article class="repair-product-group ${expanded ? "is-expanded" : ""}">
            <button type="button" class="repair-product-group__toggle" data-quality-product="${productName}" aria-expanded="${expanded}">
              <span><strong>${productName}</strong><small>${lines.length} 个规格｜仓库退回 ${formatNumber(total)}件</small></span>
              ${icons.chevron}
            </button>
            ${
              expanded
                ? `<div class="repair-quality-lines">${lines
                    .map(
                      (line) => `
                        <div class="repair-quality-line">
                          <div class="repair-quality-line__heading"><strong>${line.colorSpec}</strong><span>仓库退回 ${formatNumber(line.warehouseReturnQuantity)}件</span></div>
                          <dl>
                            <div><dt>箱号</dt><dd>${line.boxNo}</dd></div>
                            <div><dt>次品原因</dt><dd>${line.reason || "无"}</dd></div>
                          </dl>
                        </div>
                      `,
                    )
                    .join("")}</div>`
                : ""
            }
          </article>
        `;
      })
      .join("");
  }

  function renderReturnProductGroups(lines, formatNumber) {
    const groups = groupByProduct(lines);
    return Object.entries(groups)
      .map(
        ([productName, productLines]) => `
          <section class="repair-return-product">
            <header><strong>${productName}</strong><span>${productLines.length} 个规格</span></header>
            ${productLines
              .map((line) => {
                const returnedQuantity = line.repairedQuantity + line.scrappedQuantity;
                const progress = line.warehouseReturnQuantity
                  ? Math.min(100, Math.round((returnedQuantity / line.warehouseReturnQuantity) * 100))
                  : 0;
                return `
                  <div class="repair-return-line">
                    <strong>${line.colorSpec}</strong>
                    <dl>
                      <div><dt>返修</dt><dd>${formatNumber(line.repairedQuantity)}</dd></div>
                      <div><dt>报废</dt><dd>${formatNumber(line.scrappedQuantity)}</dd></div>
                    </dl>
                    <div class="repair-return-line__progress">
                      <span><small>返回进度</small><strong>${formatNumber(returnedQuantity)} / ${formatNumber(line.warehouseReturnQuantity)}</strong><em>${progress}%</em></span>
                      <i><b style="width:${progress}%"></b></i>
                    </div>
                  </div>
                `;
              })
              .join("")}
          </section>
        `,
      )
      .join("");
  }

  function renderReturnBatches(detail, state, icons, formatNumber) {
    if (!detail.returnBatches.length) {
      return `<div class="repair-detail-empty"><span>${icons.box}</span><h3>工厂尚未提交发回记录</h3><p>提交后会按发回日期分组显示。</p></div>`;
    }
    return detail.returnBatches
      .map((batch) => {
        const expanded = state.expandedRepairBatches.includes(batch.id);
        const returnedTotal = batch.lines.reduce((sum, line) => sum + line.repairedQuantity + line.scrappedQuantity, 0);
        return `
          <article class="repair-batch ${expanded ? "is-expanded" : ""}">
            <button type="button" class="repair-batch__toggle" data-return-batch="${batch.id}" aria-expanded="${expanded}">
              <span><strong>${batch.returnDate}</strong><small>${batch.lines.length} 个规格｜返回 ${formatNumber(returnedTotal)}件</small></span>
              ${icons.chevron}
            </button>
            ${expanded ? `<div class="repair-batch__content">${renderReturnProductGroups(batch.lines, formatNumber)}</div>` : ""}
          </article>
        `;
      })
      .join("");
  }

  function bindEvents(context) {
    const { state, render, navigate } = context;
    document.querySelector("#back-from-repair")?.addEventListener("click", () => navigate("repairs"));

    document.querySelectorAll("[data-repair-detail-tab]").forEach((button) => {
      button.addEventListener("click", () => {
        state.repairDetailTab = button.dataset.repairDetailTab;
        render();
      });
    });

    document.querySelectorAll("[data-quality-product]").forEach((button) => {
      button.addEventListener("click", () => {
        const productName = button.dataset.qualityProduct;
        state.expandedRepairProducts = state.expandedRepairProducts.includes(productName)
          ? state.expandedRepairProducts.filter((name) => name !== productName)
          : [...state.expandedRepairProducts, productName];
        render();
      });
    });

    document.querySelectorAll("[data-return-batch]").forEach((button) => {
      button.addEventListener("click", () => {
        const batchId = button.dataset.returnBatch;
        state.expandedRepairBatches = state.expandedRepairBatches.includes(batchId)
          ? state.expandedRepairBatches.filter((id) => id !== batchId)
          : [...state.expandedRepairBatches, batchId];
        render();
      });
    });
  }

  function mount(context) {
    const { app, data, icons, state, helpers, navigate } = context;
    const visibleRepairs = data.repairRecords.filter((record) => record.archived !== true);
    const repair = visibleRepairs.find((record) => record.repairNo === state.selectedRepairNo) ?? visibleRepairs[0];
    if (!repair) {
      navigate("repairs");
      return;
    }
    const detail = data.repairDetails[repair.repairNo];
    const returnedQuantity = repair.repairedQuantity + repair.scrappedQuantity;
    const progress = repair.warehouseReturnQuantity
      ? Math.min(100, Math.round((returnedQuantity / repair.warehouseReturnQuantity) * 100))
      : 0;

    if (state.repairDetailInitializedFor !== repair.repairNo) {
      const firstProduct = detail.qualityLines[0]?.productName;
      state.repairDetailInitializedFor = repair.repairNo;
      state.repairDetailTab = "quality";
      state.expandedRepairProducts = firstProduct ? [firstProduct] : [];
      state.expandedRepairBatches = detail.returnBatches[0] ? [detail.returnBatches[0].id] : [];
    }

    app.innerHTML = `
      <div class="repair-detail-page">
        <header class="detail-titlebar">
          <button type="button" class="back-button" id="back-from-repair" aria-label="返回">${icons.back}</button>
          <h1>返修详情</h1>
          <div class="wechat-capsule" aria-hidden="true"><b>•••</b><i></i><span></span></div>
        </header>

        <main class="repair-detail-content">
          <section class="repair-detail-summary">
            <div class="repair-detail-summary__heading"><small>工厂</small><h2>${repair.factory}</h2></div>
            <div class="repair-detail-summary__meta">
              <p><span>返修单号</span><strong>${repair.repairNo}</strong></p>
              <p><span>退回日期</span><strong>${repair.returnDate}</strong></p>
            </div>
            <div class="repair-detail-summary__stats">
              <p><span>返修数量</span><strong>${helpers.formatNumber(repair.repairedQuantity)}</strong></p>
              <p><span>报废数量</span><strong>${helpers.formatNumber(repair.scrappedQuantity)}</strong></p>
            </div>
            <div class="repair-detail-summary__progress">
              <span><small>返回进度</small><strong>${helpers.formatNumber(returnedQuantity)} / ${helpers.formatNumber(repair.warehouseReturnQuantity)}</strong><em>${progress}%</em></span>
              <i><b style="width:${progress}%"></b></i>
            </div>
          </section>

          <section class="repair-detail-records">
            <div class="repair-detail-tabs" role="tablist" aria-label="返修详情内容">
              <button type="button" class="${state.repairDetailTab === "quality" ? "is-active" : ""}" data-repair-detail-tab="quality" role="tab" aria-selected="${state.repairDetailTab === "quality"}">质检明细</button>
              <button type="button" class="${state.repairDetailTab === "returns" ? "is-active" : ""}" data-repair-detail-tab="returns" role="tab" aria-selected="${state.repairDetailTab === "returns"}">工厂发回记录</button>
            </div>
            <div class="repair-detail-panel">
              ${
                state.repairDetailTab === "quality"
                  ? renderQualityGroups(detail, state, icons, helpers.formatNumber)
                  : renderReturnBatches(detail, state, icons, helpers.formatNumber)
              }
            </div>
          </section>
        </main>
      </div>
    `;

    bindEvents(context);
  }

  window.AdminPrototypePages ??= {};
  window.AdminPrototypePages["repair-detail"] = { mount };
})();
