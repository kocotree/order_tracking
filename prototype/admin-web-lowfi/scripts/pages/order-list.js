import { orderDetailData, orderListData } from "../mock-data.js";
import { escapeHTML, showToast } from "../components/app-shell.js";
import { getNextSortState, renderSortableHeader, sortRows, updateSortHeaders } from "../components/table-sort.js";

const searchIcon = `<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><circle cx="11" cy="11" r="6.5" stroke="currentColor" stroke-width="1.7"/><path d="m16 16 4 4" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/></svg>`;
const chevronIcon = `<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="m7 9 5 5 5-5" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>`;

const statusFilters = [
  { key: "all", label: "全部" },
  { key: "incomplete", label: "未完成" },
  { key: "overdue", label: "已逾期" },
  { key: "completed", label: "已完成" },
  { key: "draft", label: "草稿" },
];

function getOrderDisplayStatus(order) {
  if (order.statusKey === "draft") return { key: "draft", label: "草稿", tone: "draft" };
  if (order.statusKey === "completed") return { key: "completed", label: "已完成", tone: "success" };
  if (order.overdueDays > 0) return { key: "overdue", label: "已逾期", tone: "danger" };
  return { key: "incomplete", label: "未完成", tone: "info" };
}

function renderStatusTabs() {
  return statusFilters
    .map(
      (item, index) => `
        <button class="order-status-tab${index === 0 ? " is-active" : ""}" type="button" aria-pressed="${String(index === 0)}" data-status-filter="${escapeHTML(item.key)}">
          ${escapeHTML(item.label)}
        </button>
      `,
    )
    .join("");
}

function renderMultiSelectOptions(values, dataAttribute) {
  return values
    .map(
      (value) => `
        <label class="order-multiselect-option">
          <input type="checkbox" value="${escapeHTML(value)}" ${dataAttribute} />
          <span>${escapeHTML(value)}</span>
        </label>
      `,
    )
    .join("");
}

function renderProgress(label, percent) {
  return `
    <div class="list-progress-cell">
      <div class="list-progress-line">
        <span class="progress-track" aria-label="${escapeHTML(label)} ${escapeHTML(percent)}%">
          <span class="progress-bar" style="width: ${escapeHTML(percent)}%"></span>
        </span>
        <span class="list-progress-percent">${escapeHTML(percent)}%</span>
      </div>
    </div>
  `;
}

function renderOrderRows(orders, rowStart = 0) {
  if (orders.length === 0) {
    return `
      <tr>
        <td colspan="11">
          <div class="empty-state">
            <div>
              <span class="empty-state-mark">0</span>
              <strong>没有符合当前条件的订单</strong>
              <p>可以调整搜索词、状态或高级筛选条件后重新查询。</p>
            </div>
          </div>
        </td>
      </tr>
    `;
  }

  return orders
    .map((order, index) => {
      const displayStatus = getOrderDisplayStatus(order);
      return `
        <tr>
          <td class="order-sequence-cell">${rowStart + index + 1}</td>
          <td>
            <button class="row-link" type="button" data-order-detail="${escapeHTML(order.orderNo)}">${escapeHTML(order.orderNo)}</button>
          </td>
          <td class="order-product-summary">
            <strong>${escapeHTML(order.productName)}</strong>
          </td>
          <td><span class="category-tag is-${order.category === "帽子" ? "hat" : "clothing"}">${escapeHTML(order.category)}</span></td>
          <td class="tracker-cell"><span class="tracker-tag" data-tracker="${escapeHTML(order.tracker)}">${escapeHTML(order.tracker)}</span></td>
          <td>${escapeHTML(order.factory)}</td>
          <td>${escapeHTML(order.nearestDue)}</td>
          <td>${renderProgress("发货进度", order.shippedPercent)}</td>
          <td class="order-shipment-count">${escapeHTML(order.shippedText)}</td>
          <td class="order-status-cell">
            <span class="status-badge is-${escapeHTML(displayStatus.tone)}">${escapeHTML(displayStatus.label)}</span>
          </td>
          <td>
            <div class="order-row-actions">
              <button class="order-view-button" type="button" data-order-detail="${escapeHTML(order.orderNo)}">详情</button>
              ${order.statusKey === "draft" ? `<button class="order-delete-button" type="button" data-delete-order="${escapeHTML(order.orderNo)}">删除</button>` : ""}
            </div>
          </td>
        </tr>
      `;
    })
    .join("");
}

function renderDeleteOrderDialog() {
  return `
    <div class="detail-confirm-layer" hidden data-order-delete-layer>
      <button class="detail-confirm-backdrop" type="button" aria-label="取消删除订单" data-order-delete-cancel></button>
      <section class="detail-confirm-dialog order-delete-dialog" role="dialog" aria-modal="true" aria-labelledby="order-delete-title" aria-describedby="order-delete-description">
        <h2 id="order-delete-title">删除订单</h2>
        <p id="order-delete-description">确认删除草稿订单 <strong data-order-delete-label></strong>？删除后无法恢复。</p>
        <div class="detail-confirm-actions">
          <button class="detail-outline-button" type="button" data-order-delete-cancel>取消</button>
          <button class="order-delete-confirm-button" type="button" data-order-delete-confirm>确认删除</button>
        </div>
      </section>
    </div>
  `;
}

function renderPagination(currentPage, totalPages, totalItems) {
  if (totalItems === 0) return `<span class="order-page-total">共 0 条</span>`;

  const pageButtons = Array.from({ length: totalPages }, (_, index) => {
    const pageNumber = index + 1;
    const isCurrent = pageNumber === currentPage;
    return `
      <button
        class="order-page-button${isCurrent ? " is-current" : ""}"
        type="button"
        aria-label="第 ${pageNumber} 页"
        aria-current="${isCurrent ? "page" : "false"}"
        data-list-page="${pageNumber}"
      >${pageNumber}</button>
    `;
  }).join("");

  return `
    <span class="order-page-total">共 ${totalItems} 条</span>
    <button class="order-page-button order-page-arrow" type="button" aria-label="上一页" data-list-page-action="prev" ${currentPage === 1 ? "disabled" : ""}>‹</button>
    ${pageButtons}
    <button class="order-page-button order-page-arrow" type="button" aria-label="下一页" data-list-page-action="next" ${currentPage === totalPages ? "disabled" : ""}>›</button>
  `;
}

export function renderOrderListPage() {
  const factories = [...new Set(orderListData.orders.flatMap((item) => item.factory.split(/[、,，]/).map((value) => value.trim())))].sort();
  const trackers = [...new Set(orderListData.orders.map((item) => item.tracker))].sort();

  return `
    <article class="order-list-page" data-order-list-page>
      <section class="order-list-filter-card" aria-label="订单筛选">
        <div class="order-status-tabs" aria-label="订单状态">
          ${renderStatusTabs()}
        </div>

        <form class="order-filter-form" data-order-list-form>
          <div class="order-filter-row">
            <label class="order-list-search-field">
              <span class="sr-only">搜索订单编号、产品名称或颜色规格</span>
              ${searchIcon}
              <input type="search" placeholder="输入订单编号、产品名称或颜色/规格" autocomplete="off" data-list-keyword />
            </label>

            <label class="order-select-field order-category-field">
              <span class="sr-only">选择分类</span>
              <select data-list-category>
                <option value="">全部分类</option>
                <option value="服装">服装</option>
                <option value="帽子">帽子</option>
              </select>
            </label>

            <div class="order-multiselect" data-list-factory>
              <button class="order-multiselect-trigger" type="button" aria-haspopup="true" aria-expanded="false" data-list-factory-trigger>
                <span data-list-factory-label>全部工厂</span>
                ${chevronIcon}
              </button>
              <div class="order-multiselect-menu" aria-hidden="true" data-list-factory-menu>
                <div class="order-multiselect-title">选择工厂（可多选）</div>
                ${renderMultiSelectOptions(factories, "data-list-factory-option")}
              </div>
            </div>

            <div class="order-multiselect order-tracker-multiselect" data-list-tracker>
              <button class="order-multiselect-trigger" type="button" aria-haspopup="true" aria-expanded="false" data-list-tracker-trigger>
                <span data-list-tracker-label>全部跟单人员</span>
                ${chevronIcon}
              </button>
              <div class="order-multiselect-menu" aria-hidden="true" data-list-tracker-menu>
                <div class="order-multiselect-title">选择跟单人员（可多选）</div>
                ${renderMultiSelectOptions(trackers, "data-list-tracker-option")}
              </div>
            </div>

            <label class="order-date-field">
              <span class="sr-only">合同出货开始日期</span>
              <input type="date" data-list-due-from />
            </label>
            <span class="order-date-separator">—</span>
            <label class="order-date-field">
              <span class="sr-only">合同出货结束日期</span>
              <input type="date" data-list-due-to />
            </label>

            <button class="order-secondary-button" type="button" data-list-reset>重置</button>
            <button class="order-primary-button" type="submit">搜索</button>
          </div>
        </form>
      </section>

      <section class="section-card order-list-card" aria-labelledby="order-list-title">
        <header class="order-list-card-header">
          <div class="order-list-heading">
            <h1 id="order-list-title">订单列表</h1>
          </div>
        </header>

        <div class="table-scroll">
          <table class="orders-table order-list-table data-grid-table">
            <thead>
              <tr>
                <th class="order-sequence-column" scope="col">序号</th>
                ${renderSortableHeader("订单编号", "orderNo")}
                ${renderSortableHeader("产品名称", "productName")}
                ${renderSortableHeader("分类", "category")}
                ${renderSortableHeader("跟单人员", "tracker")}
                ${renderSortableHeader("工厂", "factory")}
                ${renderSortableHeader("合同出货时间", "nearestDue")}
                ${renderSortableHeader("发货进度", "shippedPercent")}
                ${renderSortableHeader("已发/订单数", "shippedQuantity")}
                ${renderSortableHeader("状态", "status")}
                <th scope="col">操作</th>
              </tr>
            </thead>
            <tbody data-order-list-body>
              ${renderOrderRows(orderListData.orders)}
            </tbody>
          </table>
        </div>
        <div class="order-list-footer">
          <span>原型数据仅用于验证字段、筛选和操作顺序。</span>
          <nav class="order-pagination" aria-label="订单分页" data-list-pagination></nav>
        </div>
      </section>
      ${renderDeleteOrderDialog()}
    </article>
  `;
}

function normalizeKeyword(value) {
  return String(value).trim().toLocaleLowerCase("zh-CN");
}

function normalizeDateFilter(value) {
  const match = String(value).trim().match(/^(\d{4})[年./-](\d{1,2})[月./-](\d{1,2})日?$/);
  if (!match) return "";
  return `${match[1]}-${match[2].padStart(2, "0")}-${match[3].padStart(2, "0")}`;
}

function sortOrders(orders, sortKey) {
  const result = [...orders];
  const timeValue = (value) => new Date(value).getTime();
  const draftFirst = (a, b) => Number(b.statusKey === "draft") - Number(a.statusKey === "draft");
  const sortWithDraftFirst = (compare) => result.sort((a, b) => draftFirst(a, b) || compare(a, b));

  if (sortKey === "due-asc") return sortWithDraftFirst((a, b) => timeValue(a.nearestDue) - timeValue(b.nearestDue));
  if (sortKey === "due-desc") return sortWithDraftFirst((a, b) => timeValue(b.nearestDue) - timeValue(a.nearestDue));
  if (sortKey === "order-date-desc") return sortWithDraftFirst((a, b) => timeValue(b.orderDate) - timeValue(a.orderDate));
  if (sortKey === "updated-desc") return sortWithDraftFirst((a, b) => timeValue(b.updatedAt) - timeValue(a.updatedAt));

  const priority = (item) => {
    if (item.statusKey === "draft") return 0;
    if (item.overdueDays > 0 && item.statusKey !== "completed") return 1;
    if (["pending", "shipping"].includes(item.statusKey)) return 2;
    return 3;
  };

  return result.sort((a, b) => {
    const priorityDifference = priority(a) - priority(b);
    if (priorityDifference !== 0) return priorityDifference;
    return timeValue(a.nearestDue) - timeValue(b.nearestDue);
  });
}

function orderSortValue(order, key) {
  if (key === "status") return getOrderDisplayStatus(order).label;
  if (key === "shippedQuantity") return Number(String(order.shippedText).replace(/,/g, "").split("/")[0]) || 0;
  return order[key];
}

export function bindOrderListPage() {
  const page = document.querySelector("[data-order-list-page]");
  const form = page?.querySelector("[data-order-list-form]");
  const keywordInput = page?.querySelector("[data-list-keyword]");
  const categorySelect = page?.querySelector("[data-list-category]");
  const factoryTrigger = page?.querySelector("[data-list-factory-trigger]");
  const factoryMenu = page?.querySelector("[data-list-factory-menu]");
  const factoryLabel = page?.querySelector("[data-list-factory-label]");
  const factoryOptions = [...(page?.querySelectorAll("[data-list-factory-option]") ?? [])];
  const trackerTrigger = page?.querySelector("[data-list-tracker-trigger]");
  const trackerMenu = page?.querySelector("[data-list-tracker-menu]");
  const trackerLabel = page?.querySelector("[data-list-tracker-label]");
  const trackerOptions = [...(page?.querySelectorAll("[data-list-tracker-option]") ?? [])];
  const dueFromInput = page?.querySelector("[data-list-due-from]");
  const dueToInput = page?.querySelector("[data-list-due-to]");
  const sortSelect = page?.querySelector("[data-list-sort]");
  const tableBody = page?.querySelector("[data-order-list-body]");
  const pagination = page?.querySelector("[data-list-pagination]");
  const deleteLayer = page?.querySelector("[data-order-delete-layer]");
  const deleteOrderLabel = page?.querySelector("[data-order-delete-label]");
  let activeStatus = "all";
  let currentPage = 1;
  let currentOrders = [];
  let tableSortState = { key: null, direction: "asc" };
  let pendingDeleteOrderNo = "";
  const pageSize = 10;

  const closeDeleteDialog = () => {
    if (deleteLayer) deleteLayer.hidden = true;
    document.body.classList.remove("has-dialog-open");
    pendingDeleteOrderNo = "";
  };

  const closeFactoryMenu = () => {
    factoryMenu?.classList.remove("is-open");
    factoryMenu?.setAttribute("aria-hidden", "true");
    factoryTrigger?.setAttribute("aria-expanded", "false");
  };

  const selectedFactories = () => factoryOptions.filter((option) => option.checked).map((option) => option.value);

  const updateFactoryLabel = () => {
    const selected = selectedFactories();
    if (!factoryLabel) return;
    factoryLabel.textContent = selected.length === 0 ? "全部工厂" : selected.length === 1 ? selected[0] : `已选 ${selected.length} 个工厂`;
  };

  const closeTrackerMenu = () => {
    trackerMenu?.classList.remove("is-open");
    trackerMenu?.setAttribute("aria-hidden", "true");
    trackerTrigger?.setAttribute("aria-expanded", "false");
  };

  const selectedTrackers = () => trackerOptions.filter((option) => option.checked).map((option) => option.value);

  const updateTrackerLabel = () => {
    const selected = selectedTrackers();
    if (!trackerLabel) return;
    trackerLabel.textContent = selected.length === 0 ? "全部跟单人员" : selected.length === 1 ? selected[0] : `已选 ${selected.length} 位跟单人员`;
  };

  const renderCurrentPage = () => {
    const totalPages = Math.max(1, Math.ceil(currentOrders.length / pageSize));
    currentPage = Math.min(Math.max(currentPage, 1), totalPages);
    const pageStart = (currentPage - 1) * pageSize;
    const pageOrders = currentOrders.slice(pageStart, pageStart + pageSize);
    if (tableBody) tableBody.innerHTML = renderOrderRows(pageOrders, pageStart);
    if (pagination) pagination.innerHTML = renderPagination(currentPage, totalPages, currentOrders.length);
  };

  const applyFilters = (resetPage = true) => {
    const keyword = normalizeKeyword(keywordInput?.value ?? "");
    const category = categorySelect?.value ?? "";
    const factories = selectedFactories();
    const trackers = selectedTrackers();
    const dueFrom = normalizeDateFilter(dueFromInput?.value ?? "");
    const dueTo = normalizeDateFilter(dueToInput?.value ?? "");
    const sortKey = sortSelect?.value ?? "default";

    const filteredOrders = orderListData.orders.filter((order) => {
      const matchesKeyword = !keyword || [order.orderNo, order.productName, order.specSummary].some((value) => normalizeKeyword(value).includes(keyword));
      const matchesCategory = !category || order.category === category;
      const matchesStatus = activeStatus === "all" || getOrderDisplayStatus(order).key === activeStatus;
      const orderFactories = order.factory.split(/[、,，]/).map((value) => value.trim());
      const matchesFactory = factories.length === 0 || factories.some((factory) => orderFactories.includes(factory));
      const matchesTracker = trackers.length === 0 || trackers.includes(order.tracker);
      const matchesFrom = !dueFrom || order.nearestDue >= dueFrom;
      const matchesTo = !dueTo || order.nearestDue <= dueTo;
      return matchesKeyword && matchesCategory && matchesStatus && matchesFactory && matchesTracker && matchesFrom && matchesTo;
    });

    currentOrders = tableSortState.key
      ? sortRows(filteredOrders, tableSortState, orderSortValue)
      : sortOrders(filteredOrders, sortKey);
    if (resetPage) currentPage = 1;
    renderCurrentPage();
  };

  form?.addEventListener("submit", (event) => {
    event.preventDefault();
    applyFilters();
  });

  page?.querySelectorAll("[data-status-filter]").forEach((button) => {
    button.addEventListener("click", () => {
      activeStatus = button.dataset.statusFilter ?? "all";
      page.querySelectorAll("[data-status-filter]").forEach((item) => {
        const isActive = item === button;
        item.classList.toggle("is-active", isActive);
        item.setAttribute("aria-pressed", String(isActive));
      });
      applyFilters();
    });
  });

  [categorySelect, dueFromInput, dueToInput].forEach((control) => {
    control?.addEventListener("change", () => applyFilters());
  });

  sortSelect?.addEventListener("change", () => {
    tableSortState = { key: null, direction: "asc" };
    updateSortHeaders(page, tableSortState);
    applyFilters();
  });

  factoryOptions.forEach((option) => {
    option.addEventListener("change", () => {
      updateFactoryLabel();
      applyFilters();
    });
  });

  trackerOptions.forEach((option) => {
    option.addEventListener("change", () => {
      updateTrackerLabel();
      applyFilters();
    });
  });

  page?.querySelector("[data-list-reset]")?.addEventListener("click", () => {
    form?.reset();
    factoryOptions.forEach((option) => {
      option.checked = false;
    });
    trackerOptions.forEach((option) => {
      option.checked = false;
    });
    updateFactoryLabel();
    updateTrackerLabel();
    tableSortState = { key: null, direction: "asc" };
    updateSortHeaders(page, tableSortState);
    activeStatus = "all";
    page.querySelectorAll("[data-status-filter]").forEach((item) => {
      const isActive = item.dataset.statusFilter === "all";
      item.classList.toggle("is-active", isActive);
      item.setAttribute("aria-pressed", String(isActive));
    });
    applyFilters();
  });

  page?.addEventListener("click", (event) => {
    if (event.target.closest("[data-order-delete-cancel]")) {
      closeDeleteDialog();
      return;
    }

    const deleteOrderNo = event.target.closest("[data-delete-order]")?.dataset.deleteOrder;
    if (deleteOrderNo) {
      const order = orderListData.orders.find((item) => item.orderNo === deleteOrderNo);
      if (order?.statusKey !== "draft") {
        showToast("无法删除", "只有草稿订单可以删除。");
        return;
      }
      pendingDeleteOrderNo = deleteOrderNo;
      if (deleteOrderLabel) deleteOrderLabel.textContent = deleteOrderNo;
      if (deleteLayer) deleteLayer.hidden = false;
      document.body.classList.add("has-dialog-open");
      deleteLayer?.querySelector("[data-order-delete-confirm]")?.focus();
      return;
    }

    if (event.target.closest("[data-order-delete-confirm]")) {
      const deleteIndex = orderListData.orders.findIndex((item) => item.orderNo === pendingDeleteOrderNo && item.statusKey === "draft");
      if (deleteIndex < 0) {
        closeDeleteDialog();
        showToast("无法删除", "该订单不存在或已不再是草稿状态。");
        return;
      }
      const [deletedOrder] = orderListData.orders.splice(deleteIndex, 1);
      delete orderDetailData[deletedOrder.orderNo];
      closeDeleteDialog();
      applyFilters(false);
      showToast("删除成功", `${deletedOrder.orderNo} 草稿订单已删除。`);
      return;
    }

    const nextSortState = getNextSortState(event, tableSortState);
    if (nextSortState) {
      tableSortState = nextSortState;
      updateSortHeaders(page, tableSortState);
      applyFilters();
      return;
    }

    const factoryButton = event.target.closest("[data-list-factory-trigger]");
    if (factoryButton) {
      const isOpen = factoryMenu?.classList.toggle("is-open") ?? false;
      factoryMenu?.setAttribute("aria-hidden", String(!isOpen));
      factoryTrigger?.setAttribute("aria-expanded", String(isOpen));
      closeTrackerMenu();
      return;
    }

    const trackerButton = event.target.closest("[data-list-tracker-trigger]");
    if (trackerButton) {
      const isOpen = trackerMenu?.classList.toggle("is-open") ?? false;
      trackerMenu?.setAttribute("aria-hidden", String(!isOpen));
      trackerTrigger?.setAttribute("aria-expanded", String(isOpen));
      closeFactoryMenu();
      return;
    }

    const orderNo = event.target.closest("[data-order-detail]")?.dataset.orderDetail;
    if (orderNo) {
      window.location.hash = `/orders/${encodeURIComponent(orderNo)}`;
      return;
    }

    const pageButton = event.target.closest("[data-list-page]");
    if (pageButton) {
      currentPage = Number(pageButton.dataset.listPage) || 1;
      renderCurrentPage();
      return;
    }

    const pageAction = event.target.closest("[data-list-page-action]")?.dataset.listPageAction;
    if (pageAction) {
      currentPage += pageAction === "next" ? 1 : -1;
      renderCurrentPage();
      return;
    }

    if (!event.target.closest("[data-list-factory]")) closeFactoryMenu();
    if (!event.target.closest("[data-list-tracker]")) closeTrackerMenu();
  });

  page?.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && deleteLayer && !deleteLayer.hidden) closeDeleteDialog();
  });

  applyFilters();
}
