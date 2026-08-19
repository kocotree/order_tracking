import { repairListData } from "../mock-data.js";
import { escapeHTML, showToast } from "../components/app-shell.js";
import { getNextSortState, renderSortableHeader, sortRows, updateSortHeaders } from "../components/table-sort.js";

const searchIcon = `<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><circle cx="11" cy="11" r="6.5" stroke="currentColor" stroke-width="1.7"/><path d="m16 16 4 4" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/></svg>`;
const chevronIcon = `<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="m7 9 5 5 5-5" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>`;

function formatNumber(value) {
  return new Intl.NumberFormat("zh-CN").format(Number(value) || 0);
}

function getRepairDisplayStatus(repair) {
  return repair.statusKey === "completed"
    ? { key: "completed", label: "已完成", tone: "success" }
    : { key: "incomplete", label: "未完成", tone: "info" };
}

function renderMultiSelectOptions(values) {
  return values.map((value) => `
    <label class="order-multiselect-option">
      <input type="checkbox" value="${escapeHTML(value)}" data-repair-factory-option />
      <span>${escapeHTML(value)}</span>
    </label>
  `).join("");
}

function renderRows(repairs, rowStart = 0) {
  if (!repairs.length) {
    return `<tr><td colspan="10"><div class="empty-state"><div><span class="empty-state-mark">0</span><strong>没有符合当前条件的返修单</strong><p>可以调整返修单号、状态、工厂或退回时间范围后重新查询。</p></div></div></td></tr>`;
  }

  return repairs.map((repair, index) => {
    const returnedTotal = Number(repair.repairedQuantity) + Number(repair.scrappedQuantity);
    const displayStatus = getRepairDisplayStatus(repair);
    return `
    <tr>
      <td class="order-sequence-cell">${rowStart + index + 1}</td>
      <td><button class="row-link" type="button" data-repair-detail="${escapeHTML(repair.repairNo)}">${escapeHTML(repair.repairNo)}</button></td>
      <td>${escapeHTML(repair.factory)}</td>
      <td class="repair-number-cell">${escapeHTML(formatNumber(repair.repairedQuantity))}</td>
      <td class="repair-number-cell">${escapeHTML(formatNumber(repair.scrappedQuantity))}</td>
      <td class="repair-number-cell">${escapeHTML(formatNumber(returnedTotal))}</td>
      <td class="repair-number-cell">${escapeHTML(formatNumber(repair.warehouseReturnQuantity))}</td>
      <td>${escapeHTML(repair.returnedAt.slice(0, 10))}</td>
      <td><span class="status-badge is-${displayStatus.tone}">${displayStatus.label}</span></td>
      <td>
        <div class="order-row-actions">
          <button class="order-view-button" type="button" data-repair-detail="${escapeHTML(repair.repairNo)}">详情</button>
              ${repair.statusKey === "completed" ? `<button class="order-view-button repair-archive-button" type="button" data-repair-archive="${escapeHTML(repair.repairNo)}">归档</button>` : ""}
        </div>
      </td>
    </tr>
  `;
  }).join("");
}

function renderPagination(currentPage, totalPages, totalItems) {
  if (!totalItems) return `<span class="order-page-total">共 0 条</span>`;
  const pages = Array.from({ length: totalPages }, (_, index) => {
    const page = index + 1;
    return `<button class="order-page-button${page === currentPage ? " is-current" : ""}" type="button" aria-label="第 ${page} 页" aria-current="${page === currentPage ? "page" : "false"}" data-repair-page="${page}">${page}</button>`;
  }).join("");
  return `<span class="order-page-total">共 ${totalItems} 条</span><button class="order-page-button order-page-arrow" type="button" aria-label="上一页" data-repair-page-action="prev" ${currentPage === 1 ? "disabled" : ""}>‹</button>${pages}<button class="order-page-button order-page-arrow" type="button" aria-label="下一页" data-repair-page-action="next" ${currentPage === totalPages ? "disabled" : ""}>›</button>`;
}

function normalize(value) {
  return String(value).trim().toLocaleLowerCase("zh-CN");
}

function renderArchiveDialog() {
  return `
    <div class="detail-confirm-layer" hidden data-repair-archive-layer>
      <button class="detail-confirm-backdrop" type="button" aria-label="取消归档返修单" data-repair-archive-cancel></button>
      <section class="detail-confirm-dialog order-delete-dialog" role="dialog" aria-modal="true" aria-labelledby="repair-archive-title" aria-describedby="repair-archive-description">
        <h2 id="repair-archive-title">归档返修单</h2>
        <p id="repair-archive-description">确认归档返修单 <strong data-repair-archive-label></strong>？归档后管理员和工厂小程序均不再显示。</p>
        <div class="detail-confirm-actions">
          <button class="detail-outline-button" type="button" data-repair-archive-cancel>取消</button>
          <button class="order-primary-button" type="button" data-repair-archive-confirm>确认归档</button>
        </div>
      </section>
    </div>
  `;
}

export function renderRepairListPage() {
  const factories = [...new Set(repairListData.repairs.map((repair) => repair.factory))].sort();
  return `
    <article class="order-list-page repair-list-page" data-repair-list-page>
      <section class="order-list-filter-card repair-filter-card" aria-label="返修单筛选">
        <form class="order-filter-form" data-repair-filter-form>
          <div class="order-filter-row repair-filter-row">
            <label class="order-list-search-field">
              <span class="sr-only">搜索返修单号或工厂名称</span>${searchIcon}
              <input type="search" placeholder="输入返修单号或工厂名称" autocomplete="off" data-repair-keyword />
            </label>
            <label class="order-select-field repair-status-field">
              <span class="sr-only">选择返修状态</span>
              <select data-repair-status><option value="all">全部状态</option><option value="incomplete">未完成</option><option value="completed">已完成</option></select>
            </label>
            <div class="order-multiselect repair-factory-field" data-repair-factory>
              <button class="order-multiselect-trigger" type="button" aria-haspopup="true" aria-expanded="false" data-repair-factory-trigger>
                <span data-repair-factory-label>全部工厂</span>${chevronIcon}
              </button>
              <div class="order-multiselect-menu" aria-hidden="true" data-repair-factory-menu>
                <div class="order-multiselect-title">选择工厂（可多选）</div>
                ${renderMultiSelectOptions(factories)}
              </div>
            </div>
            <label class="order-date-field"><span class="sr-only">退回开始日期</span><input type="date" data-repair-date-from /></label>
            <span class="order-date-separator">—</span>
            <label class="order-date-field"><span class="sr-only">退回结束日期</span><input type="date" data-repair-date-to /></label>
            <button class="order-secondary-button" type="button" data-repair-reset>重置</button>
            <button class="order-primary-button" type="submit">搜索</button>
          </div>
        </form>
      </section>

      <section class="section-card order-list-card" aria-labelledby="repair-list-title">
        <header class="order-list-card-header repair-list-header">
          <div class="order-list-heading"><h1 id="repair-list-title">返修退回</h1></div>
          <button class="order-primary-button repair-create-button" type="button" data-repair-create>新建返修单</button>
        </header>
        <div class="table-scroll">
          <table class="orders-table repair-list-table data-grid-table">
            <thead>
              <tr>
                <th scope="col">序号</th>
                ${renderSortableHeader("返修单号", "repairNo")}
                ${renderSortableHeader("工厂", "factory")}
                ${renderSortableHeader("返修数量", "repairedQuantity")}
                ${renderSortableHeader("报废数量", "scrappedQuantity")}
                ${renderSortableHeader("返回总数量", "returnedTotal")}
                ${renderSortableHeader("仓库退回总数量", "warehouseReturnQuantity")}
                ${renderSortableHeader("退回时间", "returnedAt")}
                ${renderSortableHeader("状态", "status")}
                <th scope="col">操作</th>
              </tr>
            </thead>
            <tbody data-repair-list-body>${renderRows(repairListData.repairs)}</tbody>
          </table>
        </div>
        <div class="order-list-footer"><span>每页展示 10 条返修单。</span><nav class="order-pagination" aria-label="返修单分页" data-repair-pagination></nav></div>
      </section>
      ${renderArchiveDialog()}
    </article>
  `;
}

export function bindRepairListPage() {
  const page = document.querySelector("[data-repair-list-page]");
  const form = page?.querySelector("[data-repair-filter-form]");
  const keywordInput = page?.querySelector("[data-repair-keyword]");
  const statusSelect = page?.querySelector("[data-repair-status]");
  const factoryTrigger = page?.querySelector("[data-repair-factory-trigger]");
  const factoryMenu = page?.querySelector("[data-repair-factory-menu]");
  const factoryLabel = page?.querySelector("[data-repair-factory-label]");
  const factoryOptions = [...(page?.querySelectorAll("[data-repair-factory-option]") ?? [])];
  const dateFromInput = page?.querySelector("[data-repair-date-from]");
  const dateToInput = page?.querySelector("[data-repair-date-to]");
  const body = page?.querySelector("[data-repair-list-body]");
  const pagination = page?.querySelector("[data-repair-pagination]");
  const archiveLayer = page?.querySelector("[data-repair-archive-layer]");
  const archiveLabel = page?.querySelector("[data-repair-archive-label]");
  let sortState = { key: null, direction: "asc" };
  let currentPage = 1;
  let currentRepairs = [];
  let pendingArchiveRepairNo = "";
  const pageSize = 10;

  const closeArchiveDialog = () => {
    if (archiveLayer) archiveLayer.hidden = true;
    document.body.classList.remove("has-dialog-open");
    pendingArchiveRepairNo = "";
  };

  const closeFactoryMenu = () => {
    factoryMenu?.classList.remove("is-open");
    factoryMenu?.setAttribute("aria-hidden", "true");
    factoryTrigger?.setAttribute("aria-expanded", "false");
  };
  const selectedFactories = () => factoryOptions.filter((option) => option.checked).map((option) => option.value);
  const updateFactoryLabel = () => {
    const selected = selectedFactories();
    if (factoryLabel) factoryLabel.textContent = selected.length === 0 ? "全部工厂" : selected.length === 1 ? selected[0] : `已选 ${selected.length} 个工厂`;
  };
  const renderCurrentPage = () => {
    const totalPages = Math.max(1, Math.ceil(currentRepairs.length / pageSize));
    currentPage = Math.min(Math.max(currentPage, 1), totalPages);
    const start = (currentPage - 1) * pageSize;
    if (body) body.innerHTML = renderRows(currentRepairs.slice(start, start + pageSize), start);
    if (pagination) pagination.innerHTML = renderPagination(currentPage, totalPages, currentRepairs.length);
  };

  const applyFilters = () => {
    const keyword = normalize(keywordInput?.value ?? "");
    const factories = selectedFactories();
    const status = statusSelect?.value ?? "all";
    const dateFrom = dateFromInput?.value ?? "";
    const dateTo = dateToInput?.value ?? "";
    const filtered = repairListData.repairs.filter((repair) => (
      repair.archived !== true
      && (!keyword || normalize(repair.repairNo).includes(keyword) || normalize(repair.factory).includes(keyword))
      && (status === "all" || getRepairDisplayStatus(repair).key === status)
      && (!factories.length || factories.includes(repair.factory))
      && (!dateFrom || repair.returnedAt.slice(0, 10) >= dateFrom)
      && (!dateTo || repair.returnedAt.slice(0, 10) <= dateTo)
    ));
    currentRepairs = sortState.key ? sortRows(filtered, sortState, (repair, key) => {
      if (key === "returnedTotal") return Number(repair.repairedQuantity) + Number(repair.scrappedQuantity);
      if (key === "status") return getRepairDisplayStatus(repair).label;
      return repair[key];
    }) : filtered;
    currentPage = 1;
    renderCurrentPage();
  };

  form?.addEventListener("submit", (event) => {
    event.preventDefault();
    applyFilters();
  });
  [statusSelect, dateFromInput, dateToInput].forEach((input) => input?.addEventListener("change", applyFilters));
  factoryOptions.forEach((option) => option.addEventListener("change", () => {
    updateFactoryLabel();
    applyFilters();
  }));
  page?.querySelector("[data-repair-reset]")?.addEventListener("click", () => {
    form?.reset();
    factoryOptions.forEach((option) => { option.checked = false; });
    updateFactoryLabel();
    sortState = { key: null, direction: "asc" };
    updateSortHeaders(page, sortState);
    applyFilters();
  });
  page?.querySelector("[data-repair-create]")?.addEventListener("click", () => {
    window.location.hash = "/repairs/new";
  });
  page?.querySelectorAll("[data-repair-archive-cancel]").forEach((button) => button.addEventListener("click", closeArchiveDialog));
  page?.querySelector("[data-repair-archive-confirm]")?.addEventListener("click", () => {
    const repair = repairListData.repairs.find((item) => item.repairNo === pendingArchiveRepairNo);
    if (!repair || repair.statusKey !== "completed") {
      closeArchiveDialog();
      showToast("无法归档", "只有已完成的返修单可以归档。");
      return;
    }
    repair.archived = true;
    repair.archivedAt = new Date().toISOString();
    repair.archivedBy = "煎饼";
    const archivedRepairNo = repair.repairNo;
    closeArchiveDialog();
    applyFilters();
    showToast("归档成功", `${archivedRepairNo} 已从三端返修列表隐藏。`);
  });
  page?.addEventListener("click", (event) => {
    const factoryButton = event.target.closest("[data-repair-factory-trigger]");
    if (factoryButton) {
      const isOpen = factoryMenu?.classList.toggle("is-open") ?? false;
      factoryMenu?.setAttribute("aria-hidden", String(!isOpen));
      factoryTrigger?.setAttribute("aria-expanded", String(isOpen));
      return;
    }
    const nextSortState = getNextSortState(event, sortState);
    if (nextSortState) {
      sortState = nextSortState;
      updateSortHeaders(page, sortState);
      applyFilters();
      return;
    }
    const archiveRepairNo = event.target.closest("[data-repair-archive]")?.dataset.repairArchive;
    if (archiveRepairNo) {
      const repair = repairListData.repairs.find((item) => item.repairNo === archiveRepairNo);
      if (!repair || repair.statusKey !== "completed") {
        showToast("无法归档", "只有已完成的返修单可以归档。");
        return;
      }
      pendingArchiveRepairNo = archiveRepairNo;
      if (archiveLabel) archiveLabel.textContent = archiveRepairNo;
      if (archiveLayer) archiveLayer.hidden = false;
      document.body.classList.add("has-dialog-open");
      return;
    }
    const repairNo = event.target.closest("[data-repair-detail]")?.dataset.repairDetail;
    if (repairNo) {
      window.location.hash = `/repairs/${encodeURIComponent(repairNo)}`;
      return;
    }
    const pageNumber = event.target.closest("[data-repair-page]")?.dataset.repairPage;
    if (pageNumber) {
      currentPage = Number(pageNumber);
      renderCurrentPage();
      return;
    }
    const pageAction = event.target.closest("[data-repair-page-action]")?.dataset.repairPageAction;
    if (pageAction) {
      currentPage += pageAction === "next" ? 1 : -1;
      renderCurrentPage();
      return;
    }
    if (!event.target.closest("[data-repair-factory]")) closeFactoryMenu();
  });
  applyFilters();
}
