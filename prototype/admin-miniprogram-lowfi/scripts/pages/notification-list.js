(function registerNotificationListPage() {
  function escapeHTML(value) {
    return String(value)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function formatTime(value) {
    const [date, time] = String(value).split(" ");
    const [, month, day] = date.split("-");
    return `${month}月${day}日 ${time}`;
  }

  function renderNotification(item, icons) {
    return `
      <button type="button" class="notification-center-item${item.read ? "" : " is-unread"}" data-notification-id="${escapeHTML(item.id)}">
        <span class="notification-center-item__state" aria-label="${item.read ? "已读" : "未读"}"></span>
        <span class="notification-center-item__body">
          <span class="notification-center-item__meta">
            <em class="is-${escapeHTML(item.tone)}">${escapeHTML(item.category)}</em>
            <time>${escapeHTML(formatTime(item.time))}</time>
          </span>
          <strong>${escapeHTML(item.title)}</strong>
          <small>${escapeHTML(item.description)}</small>
        </span>
        <span class="notification-center-item__chevron">${icons.chevron}</span>
      </button>
    `;
  }

  function resolveTarget(notification, data) {
    if (notification.targetPage === "order-detail" && data.orders.some((item) => item.id === notification.targetId)) {
      return { selectedOrderId: notification.targetId, orderBackPage: "notifications" };
    }
    if (notification.targetPage === "shipment-detail" && data.shipmentDetails[notification.targetId]) {
      return { selectedShipmentNo: notification.targetId, shipmentBackPage: "notifications" };
    }
    if (notification.targetPage === "repair-detail" && data.repairRecords.some((item) => item.repairNo === notification.targetId && item.archived !== true)) {
      return { selectedRepairNo: notification.targetId, repairBackPage: "notifications" };
    }
    return null;
  }

  function bindEvents(context) {
    const { data, state, helpers, navigate, render } = context;
    document.querySelector("[data-back-profile]")?.addEventListener("click", () => navigate("profile"));

    document.querySelectorAll("[data-notification-status]").forEach((button) => {
      button.addEventListener("click", () => {
        state.notificationStatus = button.dataset.notificationStatus;
        state.notificationVisibleCount = 10;
        render();
      });
    });

    document.querySelectorAll("[data-notification-id]").forEach((button) => {
      button.addEventListener("click", () => {
        const notification = data.notifications.find((item) => item.id === button.dataset.notificationId);
        if (!notification) return;
        const targetValues = resolveTarget(notification, data);
        if (!targetValues) {
          helpers.showToast("目标记录暂不可用");
          return;
        }
        notification.read = true;
        navigate(notification.targetPage, targetValues);
      });
    });

    const sentinel = document.querySelector("[data-notification-more]");
    if (sentinel && "IntersectionObserver" in window) {
      const observer = new IntersectionObserver((entries) => {
        if (!entries.some((entry) => entry.isIntersecting)) return;
        observer.disconnect();
        state.notificationVisibleCount += 10;
        render();
      }, { rootMargin: "120px" });
      observer.observe(sentinel);
    }
  }

  function mount(context) {
    const { app, data, icons, state } = context;
    const filteredNotifications = state.notificationStatus === "unread"
      ? data.notifications.filter((item) => !item.read)
      : data.notifications;
    const visibleNotifications = filteredNotifications.slice(0, state.notificationVisibleCount);
    const hasMore = visibleNotifications.length < filteredNotifications.length;
    const emptyTitle = state.notificationStatus === "unread" ? "没有未读通知" : "暂无通知";
    const emptyDescription = state.notificationStatus === "unread"
      ? "新通知会在这里显示，进入对应详情后自动标记为已读。"
      : "合同出货、正常发货和质检单返修通知会在这里显示。";

    app.innerHTML = `
      <div class="notification-center-page">
        <header class="detail-titlebar">
          <button type="button" class="back-button" data-back-profile aria-label="返回我的">${icons.back}</button>
          <h1>通知中心</h1>
          <div class="wechat-capsule" aria-hidden="true"><b>•••</b><i></i><span></span></div>
        </header>

        <main class="notification-center-content">
          <div class="notification-center-tabs" role="tablist" aria-label="通知状态">
            <button type="button" class="${state.notificationStatus === "all" ? "is-active" : ""}" role="tab" aria-selected="${state.notificationStatus === "all"}" data-notification-status="all">全部</button>
            <button type="button" class="${state.notificationStatus === "unread" ? "is-active" : ""}" role="tab" aria-selected="${state.notificationStatus === "unread"}" data-notification-status="unread">未读</button>
          </div>

          ${
            visibleNotifications.length
              ? `<section class="notification-center-list" aria-label="通知列表">${visibleNotifications.map((item) => renderNotification(item, icons)).join("")}</section>${hasMore ? `<div class="notification-center-more" data-notification-more>继续上滑加载</div>` : `<div class="notification-center-end">已显示全部通知</div>`}`
              : `<section class="notification-center-empty"><span>${icons.bell}</span><h2>${emptyTitle}</h2><p>${emptyDescription}</p></section>`
          }
        </main>
      </div>
      <div class="prototype-toast" role="status"></div>
    `;

    bindEvents(context);
  }

  window.AdminPrototypePages ??= {};
  window.AdminPrototypePages.notifications = { mount };
})();
