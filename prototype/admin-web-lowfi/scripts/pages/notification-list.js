import { notificationData } from "../mock-data.js?v=20260827-s11-notifications";
import { escapeHTML } from "../components/app-shell.js";
import { buildRouteWithReturn } from "../router.js";

let activeStatus = "all";
let currentPage = 1;

function renderPagination(currentPage, totalPages, totalItems) {
  if (totalItems === 0) return `<span class="order-page-total">共 0 条</span>`;
  const pages = Array.from({ length: totalPages }, (_, index) => {
    const page = index + 1;
    return `<button class="order-page-button${page === currentPage ? " is-current" : ""}" type="button" aria-label="第 ${page} 页" aria-current="${page === currentPage ? "page" : "false"}" data-notification-page-number="${page}">${page}</button>`;
  }).join("");
  return `<span class="order-page-total">共 ${totalItems} 条</span><button class="order-page-button order-page-arrow" type="button" aria-label="上一页" data-notification-page-action="prev" ${currentPage === 1 ? "disabled" : ""}>‹</button>${pages}<button class="order-page-button order-page-arrow" type="button" aria-label="下一页" data-notification-page-action="next" ${currentPage === totalPages ? "disabled" : ""}>›</button>`;
}

function renderNotifications(notifications, activeStatus) {
  if (notifications.length === 0) {
    const isUnread = activeStatus === "unread";
    return `
      <div class="notification-record-empty">
        <span class="notification-record-empty-mark">0</span>
        <strong>${isUnread ? "没有未读通知" : "暂无通知"}</strong>
        <p>${isUnread ? "新通知会在这里显示，点击后会自动标记为已读。" : "合同出货提醒、发货和返修通知会在这里统一显示。"}</p>
      </div>
    `;
  }

  return notifications.map((item) => `
    <button class="notification-record-item${item.read ? "" : " is-unread"}" type="button" data-notification-record="${escapeHTML(item.id)}">
      <span class="notification-record-state" aria-label="${item.read ? "已读" : "未读"}"></span>
      <span class="notification-record-category is-${escapeHTML(item.tone)}">${escapeHTML(item.category)}</span>
      <span class="notification-record-copy">
        <strong>${escapeHTML(item.title)}</strong>
        <span>${escapeHTML(item.description)}</span>
      </span>
      <time datetime="${escapeHTML(item.time.replace(" ", "T"))}">${escapeHTML(item.time)}</time>
    </button>
  `).join("");
}

export function renderNotificationListPage() {
  return `
    <article class="notification-record-page" data-notification-record-page>
      <section class="section-card notification-record-card" aria-labelledby="notification-record-title">
        <header class="notification-record-header">
          <h1 id="notification-record-title">通知记录</h1>
          <div class="notification-record-tabs" role="tablist" aria-label="通知状态">
            <button class="notification-record-tab${activeStatus === "all" ? " is-active" : ""}" type="button" role="tab" aria-selected="${activeStatus === "all"}" data-notification-status="all">全部</button>
            <button class="notification-record-tab${activeStatus === "unread" ? " is-active" : ""}" type="button" role="tab" aria-selected="${activeStatus === "unread"}" data-notification-status="unread">未读</button>
          </div>
        </header>
        <div class="notification-record-list" data-notification-record-list></div>
        <footer class="order-list-footer notification-record-footer">
          <span>每页展示 10 条通知。</span>
          <nav class="order-pagination" aria-label="通知记录分页" data-notification-pagination></nav>
        </footer>
      </section>
    </article>
  `;
}

export function bindNotificationListPage() {
  const page = document.querySelector("[data-notification-record-page]");
  const list = page?.querySelector("[data-notification-record-list]");
  const pagination = page?.querySelector("[data-notification-pagination]");
  const pageSize = 10;

  const renderPage = () => {
    const filteredNotifications = activeStatus === "unread"
      ? notificationData.filter((item) => !item.read)
      : notificationData;
    const totalPages = Math.max(1, Math.ceil(filteredNotifications.length / pageSize));
    currentPage = Math.min(Math.max(currentPage, 1), totalPages);
    const start = (currentPage - 1) * pageSize;
    if (list) list.innerHTML = renderNotifications(filteredNotifications.slice(start, start + pageSize), activeStatus);
    if (pagination) pagination.innerHTML = renderPagination(currentPage, totalPages, filteredNotifications.length);
  };

  page?.addEventListener("click", (event) => {
    const nextStatus = event.target.closest("[data-notification-status]")?.dataset.notificationStatus;
    if (nextStatus) {
      activeStatus = nextStatus;
      currentPage = 1;
      page.querySelectorAll("[data-notification-status]").forEach((tab) => {
        const isActive = tab.dataset.notificationStatus === activeStatus;
        tab.classList.toggle("is-active", isActive);
        tab.setAttribute("aria-selected", String(isActive));
      });
      renderPage();
      return;
    }

    const notificationId = event.target.closest("[data-notification-record]")?.dataset.notificationRecord;
    if (notificationId) {
      const notification = notificationData.find((item) => item.id === notificationId);
      if (!notification) return;
      notification.read = true;
      window.location.hash = buildRouteWithReturn(notification.route, "/notifications");
      return;
    }

    const pageNumber = event.target.closest("[data-notification-page-number]")?.dataset.notificationPageNumber;
    if (pageNumber) {
      currentPage = Number(pageNumber);
      renderPage();
      return;
    }

    const pageAction = event.target.closest("[data-notification-page-action]")?.dataset.notificationPageAction;
    if (pageAction) {
      currentPage += pageAction === "next" ? 1 : -1;
      renderPage();
    }
  });

  renderPage();
}
