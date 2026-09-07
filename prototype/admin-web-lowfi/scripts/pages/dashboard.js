import { dashboardData, notificationData } from "../mock-data.js";
import { escapeHTML, showToast } from "../components/app-shell.js";
import { getNextSortState, renderSortableHeader, sortRows, updateSortHeaders } from "../components/table-sort.js";
import { buildRouteWithReturn } from "../router.js";

const searchIcon = `<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><circle cx="11" cy="11" r="6.5" stroke="currentColor" stroke-width="1.7"/><path d="m16 16 4 4" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/></svg>`;

function renderStats() {
  const today = new Date().toLocaleDateString("sv-SE", { timeZone: "Asia/Shanghai" });
  const entries = [
    { label: "待导入订单", route: "/pending-imports" },
    { label: "今日发货记录", route: `/shipments?dateFrom=${today}&dateTo=${today}` },
    { label: "逾期订单", route: "/orders?status=已逾期" },
  ];
  return entries.map((entry, index) => `<a class="dashboard-stat-card" href="#${entry.route}"><span>${entry.label}</span><strong>${dashboardData.stats[index]?.value ?? 0}</strong></a>`).join("");
}

function renderNotifications() {
  const items = [...notificationData].filter(item => !item.read).sort((a, b) => b.time.localeCompare(a.time)).slice(0, 3);
  if (!items.length) return '<div class="dashboard-notification-empty"><strong>暂无通知</strong></div>';
  return items.map(item => `<button type="button" data-notification-id="${escapeHTML(item.id)}" data-route="${escapeHTML(buildRouteWithReturn(item.route, "/dashboard"))}"><i aria-hidden="true"></i><span><strong>${escapeHTML(item.title)}</strong><small>${escapeHTML(item.description)}</small></span><time>${escapeHTML(item.time)}</time></button>`).join("");
}

function renderOrderRows(orders) {
  if (orders.length === 0) {
    return `
      <tr>
        <td colspan="10">
          <div class="empty-state">
            <div>
              <span class="empty-state-mark">0</span>
              <strong>没有匹配的订单</strong>
              <p>搜索只匹配订单编号和产品名称，不匹配工厂或跟单人员。</p>
            </div>
          </div>
        </td>
      </tr>
    `;
  }

  return orders.slice(0, 10)
    .map(
      (order, index) => `
        <tr>
          <td class="dashboard-sequence-cell">${index + 1}</td>
          <td>
            <button class="dashboard-order-link" type="button" title="${escapeHTML(order.orderNo)}" data-dashboard-order="${escapeHTML(order.orderNo)}">${escapeHTML(order.orderNo)}</button>
          </td>
          <td class="dashboard-product-cell">
            <strong>${escapeHTML(order.productName)}</strong>
          </td>
          <td><span class="dashboard-category-tag" data-category="${escapeHTML(order.category)}">${escapeHTML(order.category)}</span></td>
          <td class="tracker-cell"><span class="dashboard-tracker-tag" data-tracker="${escapeHTML(order.tracker)}">${escapeHTML(order.tracker)}</span></td>
          <td>${escapeHTML(order.factory)}</td>
          <td>${escapeHTML(order.nearestDue)}</td>
          <td>
            <div class="dashboard-progress-cell"><span><i style="width: ${escapeHTML(order.progress)}%"></i></span><em>${escapeHTML(order.progress)}%</em></div>
          </td>
          <td>${escapeHTML(order.progressText)}</td>
          <td><span class="order-status" data-status="${escapeHTML(order.status)}">${escapeHTML(order.status)}</span></td>
        </tr>
      `,
    )
    .join("");
}

function orderSortValue(order, key) {
  const values = {
    orderNo: order.orderNo,
    productName: order.productName,
    category: order.category,
    tracker: order.tracker,
    factory: order.factory,
    nearestDue: order.nearestDue,
    progress: order.progress,
    progressText: Number(String(order.progressText).replace(/,/g, "").split("/")[0]) || 0,
    status: order.status,
  };
  return values[key];
}

export function renderDashboardPage() {
  return `
    <article class="dashboard-page" data-dashboard-page>
      <section class="dashboard-search-panel" aria-label="订单快速搜索">
        <form class="dashboard-search-form" role="search" data-order-search-form>
          <label class="dashboard-search-field">
            <span class="sr-only">搜索订单编号或产品名称</span>
            ${searchIcon}
            <input class="dashboard-search-input" type="search" placeholder="输入订单编号或产品名称" autocomplete="off" data-order-search-input />
            <button class="dashboard-search-clear" type="button" aria-label="清除搜索" data-search-clear>×</button>
          </label>
          <button class="dashboard-search-submit" type="submit">搜索</button>
        </form>
      </section>

      <div class="dashboard-search-summary" role="status" data-search-summary></div>

      <div class="dashboard-overview">
        <section class="dashboard-stat-grid" aria-label="订单统计">
          ${renderStats()}
        </section>

        <section class="section-card dashboard-notification-card" aria-labelledby="notifications-title">
          <header class="dashboard-section-header">
            <div>
              <h2 class="section-title" id="notifications-title">最近通知</h2>
            </div>
            <button class="text-button" type="button" data-route="/notifications">全部通知</button>
          </header>
          <div class="dashboard-notification-list">
            ${renderNotifications()}
          </div>
        </section>
      </div>

      <section class="section-card dashboard-orders-card" aria-labelledby="orders-title">
        <header class="dashboard-section-header">
          <div class="orders-heading">
            <h2 class="section-title" id="orders-title">订单</h2>
          </div>
          <button class="text-button" type="button" data-route="/orders">查看全部订单</button>
        </header>
        <div class="table-scroll">
          <table class="dashboard-order-table data-grid-table">
            <thead>
              <tr>
                <th class="dashboard-sequence-column" scope="col">序号</th>
                ${renderSortableHeader("订单编号", "orderNo")}
                ${renderSortableHeader("产品名称", "productName")}
                ${renderSortableHeader("分类", "category")}
                ${renderSortableHeader("跟单人员", "tracker")}
                ${renderSortableHeader("工厂", "factory")}
                ${renderSortableHeader("合同出货时间", "nearestDue")}
                ${renderSortableHeader("发货进度", "progress")}
                ${renderSortableHeader("已发 / 订单数", "progressText")}
                ${renderSortableHeader("状态", "status")}
              </tr>
            </thead>
            <tbody data-order-table-body>
              ${renderOrderRows(dashboardData.orders.slice(0, 10))}
            </tbody>
          </table>
        </div>
      </section>
    </article>
  `;
}

function normalizeKeyword(value) {
  return value.trim().toLocaleLowerCase("zh-CN");
}

function matchesKeyword(item, keyword) {
  if (!keyword) return true;
  return [item.orderNo, item.productName].some((value) =>
    String(value).toLocaleLowerCase("zh-CN").includes(keyword),
  );
}

export function bindDashboardPage() {
  const page = document.querySelector("[data-dashboard-page]");
  const form = document.querySelector("[data-order-search-form]");
  const input = document.querySelector("[data-order-search-input]");
  const clearButton = document.querySelector("[data-search-clear]");
  const orderTableBody = document.querySelector("[data-order-table-body]");
  const summary = document.querySelector("[data-search-summary]");
  let currentOrders = [...dashboardData.orders];
  let sortState = { key: null, direction: "asc" };

  const renderOrders = () => {
    if (orderTableBody) orderTableBody.innerHTML = renderOrderRows(sortRows(currentOrders, sortState, orderSortValue).slice(0, 10));
  };

  const applySearch = () => {
    const rawKeyword = input?.value ?? "";
    const keyword = normalizeKeyword(rawKeyword);
    currentOrders = dashboardData.orders.filter((item) => matchesKeyword(item, keyword));
    renderOrders();

    clearButton?.classList.toggle("is-visible", Boolean(rawKeyword));
    if (!summary) return;

    if (!keyword) {
      summary.classList.remove("is-visible");
      summary.textContent = "";
      return;
    }

    summary.classList.add("is-visible");
    summary.textContent = `“${rawKeyword.trim()}”找到 ${currentOrders.length} 个订单。`;
  };

  form?.addEventListener("submit", (event) => {
    event.preventDefault();
    applySearch();
  });

  input?.addEventListener("input", () => {
    clearButton?.classList.toggle("is-visible", Boolean(input.value));
  });

  clearButton?.addEventListener("click", () => {
    if (!input) return;
    input.value = "";
    input.focus();
    applySearch();
  });

  page?.addEventListener("click", (event) => {
    const notificationId = event.target.closest("[data-notification-id]")?.dataset.notificationId;
    if (notificationId) {
      const notification = notificationData.find((item) => item.id === notificationId);
      if (notification) notification.read = true;
      return;
    }

    const nextSortState = getNextSortState(event, sortState);
    if (nextSortState) {
      sortState = nextSortState;
      updateSortHeaders(page, sortState);
      renderOrders();
      return;
    }

    const orderNo = event.target.closest("[data-dashboard-order]")?.dataset.dashboardOrder;
    if (orderNo) { window.location.hash = `/orders/${encodeURIComponent(orderNo)}`; return; }
    const destination = event.target.closest("[data-destination]")?.dataset.destination;
    if (destination) {
      showToast("目标页面待设计", `${destination}将在对应页面完成后开放。`);
      return;
    }

    const pendingAction = event.target.closest("[data-pending-action]")?.dataset.pendingAction;
    if (pendingAction) {
      showToast("功能待设计", `${pendingAction}会在“订单与发货”页面设计时补充。`);
    }
  });
}
