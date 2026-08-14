import { importPendingOrdersAsDrafts, pendingImportData } from "../mock-data.js";
import { escapeHTML, showToast } from "../components/app-shell.js";

const searchIcon = `<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><circle cx="11" cy="11" r="6.5" stroke="currentColor" stroke-width="1.7"/><path d="m16 16 4 4" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/></svg>`;
const chevronIcon = `<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="m7 9 5 5 5-5" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>`;

function renderMultiSelectOptions(values, attribute) {
  return values.map((value) => `
    <label class="order-multiselect-option">
      <input type="checkbox" value="${escapeHTML(value)}" ${attribute} />
      <span>${escapeHTML(value)}</span>
    </label>
  `).join("");
}

function renderRows(orders, rowStart = 0, selectedOrderNos = new Set()) {
  if (orders.length === 0) {
    return `<tr><td colspan="9"><div class="empty-state"><div><span class="empty-state-mark">0</span><strong>没有符合当前条件的待导入订单</strong><p>可以调整搜索词或筛选条件后重新查询。</p></div></div></td></tr>`;
  }

  return orders.map((order, index) => {
    const canSelect = order.statusKey === "pending" && order.validationKey === "ready";
    const isSelected = canSelect && selectedOrderNos.has(order.orderNo);
    return `
    <tr${isSelected ? " class=\"is-selected\"" : ""}>
      <td class="pending-import-select-cell"><input type="checkbox" aria-label="选择订单 ${escapeHTML(order.orderNo)}" data-import-select="${escapeHTML(order.orderNo)}" ${canSelect ? "" : "disabled"} ${isSelected ? "checked" : ""} /></td>
      <td class="order-sequence-cell">${rowStart + index + 1}</td>
      <td><button class="row-link" type="button" data-import-detail="${escapeHTML(order.orderNo)}">${escapeHTML(order.orderNo)}</button></td>
      <td class="order-product-summary"><strong>${escapeHTML(order.productName)}</strong></td>
      <td><span class="category-tag is-${order.category === "帽子" ? "hat" : "clothing"}">${escapeHTML(order.category)}</span></td>
      <td class="tracker-cell"><span class="tracker-tag" data-tracker="${escapeHTML(order.tracker)}">${escapeHTML(order.tracker)}</span></td>
      <td>${escapeHTML(order.factory)}</td>
      <td><span class="status-badge is-${escapeHTML(order.tone)}">${escapeHTML(order.validationLabel)}</span></td>
      <td><button class="order-view-button" type="button" data-import-detail="${escapeHTML(order.orderNo)}">查看详情</button></td>
    </tr>
  `;
  }).join("");
}

function renderPagination(currentPage, totalPages, totalItems) {
  if (totalItems === 0) return `<span class="order-page-total">共 0 条</span>`;
  const pages = Array.from({ length: totalPages }, (_, index) => {
    const page = index + 1;
    return `<button class="order-page-button${page === currentPage ? " is-current" : ""}" type="button" aria-label="第 ${page} 页" aria-current="${page === currentPage ? "page" : "false"}" data-import-page="${page}">${page}</button>`;
  }).join("");
  return `<span class="order-page-total">共 ${totalItems} 条</span><button class="order-page-button order-page-arrow" type="button" aria-label="上一页" data-import-page-action="prev" ${currentPage === 1 ? "disabled" : ""}>‹</button>${pages}<button class="order-page-button order-page-arrow" type="button" aria-label="下一页" data-import-page-action="next" ${currentPage === totalPages ? "disabled" : ""}>›</button>`;
}

function renderBatchImportDialog() {
  return `
    <div class="detail-confirm-layer" hidden data-batch-import-layer>
      <button class="detail-confirm-backdrop" type="button" aria-label="取消批量导入" data-batch-import-cancel></button>
      <section class="detail-confirm-dialog" role="dialog" aria-modal="true" aria-labelledby="batch-import-title" aria-describedby="batch-import-description">
        <h2 id="batch-import-title">确认批量导入</h2>
        <p id="batch-import-description">确认将已选 <strong data-batch-import-count>0</strong> 个订单导入跟单系统？导入后将生成草稿订单。</p>
        <p class="batch-import-order-list" data-batch-import-orders></p>
        <div class="detail-confirm-actions">
          <button class="detail-outline-button" type="button" data-batch-import-cancel>取消</button>
          <button class="detail-primary-button" type="button" data-batch-import-submit>确认批量导入</button>
        </div>
      </section>
    </div>
  `;
}

export function renderPendingImportListPage() {
  const factories = [...new Set(pendingImportData.orders.flatMap((item) => item.factory.split(/[、,，]/).map((value) => value.trim())))].sort();
  const trackers = [...new Set(pendingImportData.orders.map((item) => item.tracker))].sort();

  return `
    <article class="order-list-page pending-import-page" data-pending-import-page>
      <section class="order-list-filter-card" aria-label="待导入订单筛选">
        <div class="order-status-tabs" aria-label="待导入订单状态">
          <button class="order-status-tab is-active" type="button" aria-pressed="true" data-import-status="pending">待处理</button>
          <button class="order-status-tab" type="button" aria-pressed="false" data-import-status="ignored">已忽略</button>
        </div>
        <form class="order-filter-form" data-import-form>
          <div class="order-filter-row pending-import-filter-row">
            <label class="order-list-search-field">
              <span class="sr-only">搜索订单编号或产品名称</span>${searchIcon}
              <input type="search" placeholder="输入订单编号或产品名称" autocomplete="off" data-import-keyword />
            </label>
            <label class="order-select-field order-category-field"><span class="sr-only">选择分类</span><select data-import-category><option value="">全部分类</option><option value="服装">服装</option><option value="帽子">帽子</option></select></label>
            <div class="order-multiselect" data-import-factory>
              <button class="order-multiselect-trigger" type="button" aria-haspopup="true" aria-expanded="false" data-import-factory-trigger><span data-import-factory-label>全部工厂</span>${chevronIcon}</button>
              <div class="order-multiselect-menu" aria-hidden="true" data-import-factory-menu><div class="order-multiselect-title">选择工厂（可多选）</div>${renderMultiSelectOptions(factories, "data-import-factory-option")}</div>
            </div>
            <div class="order-multiselect order-tracker-multiselect" data-import-tracker>
              <button class="order-multiselect-trigger" type="button" aria-haspopup="true" aria-expanded="false" data-import-tracker-trigger><span data-import-tracker-label>全部跟单人员</span>${chevronIcon}</button>
              <div class="order-multiselect-menu" aria-hidden="true" data-import-tracker-menu><div class="order-multiselect-title">选择跟单人员（可多选）</div>${renderMultiSelectOptions(trackers, "data-import-tracker-option")}</div>
            </div>
            <label class="order-select-field order-validation-field"><span class="sr-only">选择校验状态</span><select data-import-validation><option value="">全部校验状态</option><option value="ready">可导入</option><option value="needs-data">资料待处理</option></select></label>
            <button class="order-secondary-button" type="button" data-import-reset>重置</button>
            <button class="order-primary-button" type="submit">搜索</button>
          </div>
        </form>
      </section>

      <section class="section-card order-list-card" aria-labelledby="pending-import-title">
        <header class="order-list-card-header">
          <div class="order-list-heading"><h1 id="pending-import-title">待导入订单</h1></div>
          <div class="order-list-header-actions">
            <button class="order-primary-button" type="button" data-batch-import-open disabled>批量导入</button>
          </div>
        </header>
        <div class="table-scroll">
          <table class="orders-table pending-import-table">
            <thead><tr><th class="pending-import-select-column" scope="col"><input type="checkbox" aria-label="全选当前页可导入订单" data-import-select-page /></th><th scope="col">序号</th><th scope="col">订单编号</th><th scope="col">产品名称</th><th scope="col">分类</th><th scope="col">跟单人员</th><th scope="col">工厂</th><th scope="col">校验状态</th><th scope="col">操作</th></tr></thead>
            <tbody data-import-body>${renderRows(pendingImportData.orders.filter((item) => item.statusKey === "pending"))}</tbody>
          </table>
        </div>
        <div class="order-list-footer"><span>每页展示 10 条待导入订单。</span><nav class="order-pagination" aria-label="待导入订单分页" data-import-pagination></nav></div>
      </section>
      ${renderBatchImportDialog()}
    </article>
  `;
}

function normalize(value) {
  return String(value).trim().toLocaleLowerCase("zh-CN");
}

export function bindPendingImportListPage() {
  const page = document.querySelector("[data-pending-import-page]");
  const form = page?.querySelector("[data-import-form]");
  const keywordInput = page?.querySelector("[data-import-keyword]");
  const categorySelect = page?.querySelector("[data-import-category]");
  const validationSelect = page?.querySelector("[data-import-validation]");
  const body = page?.querySelector("[data-import-body]");
  const pagination = page?.querySelector("[data-import-pagination]");
  const factoryTrigger = page?.querySelector("[data-import-factory-trigger]");
  const factoryMenu = page?.querySelector("[data-import-factory-menu]");
  const factoryLabel = page?.querySelector("[data-import-factory-label]");
  const factoryOptions = [...(page?.querySelectorAll("[data-import-factory-option]") ?? [])];
  const trackerTrigger = page?.querySelector("[data-import-tracker-trigger]");
  const trackerMenu = page?.querySelector("[data-import-tracker-menu]");
  const trackerLabel = page?.querySelector("[data-import-tracker-label]");
  const trackerOptions = [...(page?.querySelectorAll("[data-import-tracker-option]") ?? [])];
  const selectPageInput = page?.querySelector("[data-import-select-page]");
  const batchImportButton = page?.querySelector("[data-batch-import-open]");
  const batchImportLayer = page?.querySelector("[data-batch-import-layer]");
  const batchImportCount = page?.querySelector("[data-batch-import-count]");
  const batchImportOrders = page?.querySelector("[data-batch-import-orders]");
  let activeStatus = "pending";
  let currentPage = 1;
  let currentOrders = [];
  let currentPageOrders = [];
  const selectedOrderNos = new Set();
  const pageSize = 10;

  const selected = (options) => options.filter((item) => item.checked).map((item) => item.value);
  const closeMenu = (menu, trigger) => { menu?.classList.remove("is-open"); menu?.setAttribute("aria-hidden", "true"); trigger?.setAttribute("aria-expanded", "false"); };
  const updateLabel = (label, values, empty, unit) => { if (label) label.textContent = values.length === 0 ? empty : values.length === 1 ? values[0] : `已选 ${values.length} ${unit}`; };

  const updateSelectionControls = () => {
    const selectableOrders = currentPageOrders.filter((order) => order.statusKey === "pending" && order.validationKey === "ready");
    const selectedOnPage = selectableOrders.filter((order) => selectedOrderNos.has(order.orderNo));
    if (selectPageInput) {
      selectPageInput.checked = selectableOrders.length > 0 && selectedOnPage.length === selectableOrders.length;
      selectPageInput.indeterminate = selectedOnPage.length > 0 && selectedOnPage.length < selectableOrders.length;
      selectPageInput.disabled = selectableOrders.length === 0;
    }
    if (batchImportButton) batchImportButton.disabled = selectedOrderNos.size === 0;
  };

  const renderPage = () => {
    const totalPages = Math.max(1, Math.ceil(currentOrders.length / pageSize));
    currentPage = Math.min(Math.max(currentPage, 1), totalPages);
    const start = (currentPage - 1) * pageSize;
    currentPageOrders = currentOrders.slice(start, start + pageSize);
    if (body) body.innerHTML = renderRows(currentPageOrders, start, selectedOrderNos);
    if (pagination) pagination.innerHTML = renderPagination(currentPage, totalPages, currentOrders.length);
    updateSelectionControls();
  };

  const applyFilters = (clearSelection = true) => {
    if (clearSelection) selectedOrderNos.clear();
    const keyword = normalize(keywordInput?.value ?? "");
    const category = categorySelect?.value ?? "";
    const validation = validationSelect?.value ?? "";
    const factories = selected(factoryOptions);
    const trackers = selected(trackerOptions);
    currentOrders = pendingImportData.orders.filter((order) => {
      const orderFactories = order.factory.split(/[、,，]/).map((value) => value.trim());
      return order.statusKey === activeStatus
        && (!keyword || [order.orderNo, order.productName].some((value) => normalize(value).includes(keyword)))
        && (!category || order.category === category)
        && (!validation || order.validationKey === validation)
        && (factories.length === 0 || factories.some((factory) => orderFactories.includes(factory)))
        && (trackers.length === 0 || trackers.includes(order.tracker));
    });
    currentPage = 1;
    renderPage();
  };

  const closeBatchImportDialog = () => {
    if (batchImportLayer) batchImportLayer.hidden = true;
    document.body.classList.remove("has-dialog-open");
    batchImportButton?.focus();
  };

  form?.addEventListener("submit", (event) => { event.preventDefault(); applyFilters(); });
  categorySelect?.addEventListener("change", applyFilters);
  validationSelect?.addEventListener("change", applyFilters);
  factoryOptions.forEach((option) => option.addEventListener("change", () => { updateLabel(factoryLabel, selected(factoryOptions), "全部工厂", "个工厂"); applyFilters(); }));
  trackerOptions.forEach((option) => option.addEventListener("change", () => { updateLabel(trackerLabel, selected(trackerOptions), "全部跟单人员", "位跟单人员"); applyFilters(); }));

  page?.querySelectorAll("[data-import-status]").forEach((button) => button.addEventListener("click", () => {
    activeStatus = button.dataset.importStatus ?? "pending";
    page.querySelectorAll("[data-import-status]").forEach((item) => { const active = item === button; item.classList.toggle("is-active", active); item.setAttribute("aria-pressed", String(active)); });
    applyFilters();
  }));

  page?.querySelector("[data-import-reset]")?.addEventListener("click", () => {
    form?.reset();
    [...factoryOptions, ...trackerOptions].forEach((option) => { option.checked = false; });
    updateLabel(factoryLabel, [], "全部工厂", "个工厂");
    updateLabel(trackerLabel, [], "全部跟单人员", "位跟单人员");
    applyFilters();
  });

  selectPageInput?.addEventListener("change", () => {
    currentPageOrders
      .filter((order) => order.statusKey === "pending" && order.validationKey === "ready")
      .forEach((order) => {
        if (selectPageInput.checked) selectedOrderNos.add(order.orderNo);
        else selectedOrderNos.delete(order.orderNo);
      });
    renderPage();
  });

  batchImportButton?.addEventListener("click", () => {
    if (batchImportButton.disabled || !batchImportLayer) return;
    const orderNos = [...selectedOrderNos];
    if (batchImportCount) batchImportCount.textContent = String(orderNos.length);
    if (batchImportOrders) batchImportOrders.textContent = `已选订单：${orderNos.join("、")}`;
    batchImportLayer.hidden = false;
    document.body.classList.add("has-dialog-open");
    batchImportLayer.querySelector("[data-batch-import-submit]")?.focus();
  });

  page?.querySelectorAll("[data-batch-import-cancel]").forEach((button) => button.addEventListener("click", closeBatchImportDialog));
  page?.querySelector("[data-batch-import-submit]")?.addEventListener("click", () => {
    const importedOrders = importPendingOrdersAsDrafts([...selectedOrderNos]);
    closeBatchImportDialog();
    applyFilters();
    showToast("批量导入成功", `已导入 ${importedOrders.length} 个订单并生成草稿，可在订单列表查看。`);
  });

  page?.addEventListener("click", (event) => {
    if (event.target.closest("[data-import-factory-trigger]")) { const open = factoryMenu?.classList.toggle("is-open") ?? false; factoryMenu?.setAttribute("aria-hidden", String(!open)); factoryTrigger?.setAttribute("aria-expanded", String(open)); closeMenu(trackerMenu, trackerTrigger); return; }
    if (event.target.closest("[data-import-tracker-trigger]")) { const open = trackerMenu?.classList.toggle("is-open") ?? false; trackerMenu?.setAttribute("aria-hidden", String(!open)); trackerTrigger?.setAttribute("aria-expanded", String(open)); closeMenu(factoryMenu, factoryTrigger); return; }
    const orderNo = event.target.closest("[data-import-detail]")?.dataset.importDetail;
    if (orderNo) { window.location.hash = `/pending-imports/${encodeURIComponent(orderNo)}`; return; }
    const pageNumber = event.target.closest("[data-import-page]")?.dataset.importPage;
    if (pageNumber) { currentPage = Number(pageNumber); renderPage(); return; }
    const action = event.target.closest("[data-import-page-action]")?.dataset.importPageAction;
    if (action) { currentPage += action === "next" ? 1 : -1; renderPage(); return; }
    if (!event.target.closest("[data-import-factory]")) closeMenu(factoryMenu, factoryTrigger);
    if (!event.target.closest("[data-import-tracker]")) closeMenu(trackerMenu, trackerTrigger);
  });

  page?.addEventListener("change", (event) => {
    const orderNo = event.target.closest("[data-import-select]")?.dataset.importSelect;
    if (!orderNo) return;
    if (event.target.checked) selectedOrderNos.add(orderNo);
    else selectedOrderNos.delete(orderNo);
    renderPage();
  });

  page?.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && batchImportLayer && !batchImportLayer.hidden) closeBatchImportDialog();
  });

  applyFilters();
}
