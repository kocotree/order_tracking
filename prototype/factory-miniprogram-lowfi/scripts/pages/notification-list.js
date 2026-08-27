(function registerFactoryNotificationListPage() {
  var notificationState = { status: "all", visibleCount: 10 };

  function escapeHtml(value) {
    return String(value).replace(/[&<>'"]/g, function (char) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" }[char];
    });
  }

  function formatTime(value) {
    var parts = String(value).split(" ");
    var dateParts = parts[0].split("-");
    return dateParts[1] + "月" + dateParts[2] + "日 " + parts[1];
  }

  function renderNotification(item, icons) {
    return '<button type="button" class="factory-notification-item' + (item.read ? '' : ' is-unread') + '" data-notification-id="' + escapeHtml(item.id) + '">' +
      '<span class="factory-notification-item__state" aria-label="' + (item.read ? '已读' : '未读') + '"></span>' +
      '<span class="factory-notification-item__body"><span class="factory-notification-item__meta"><em class="is-' + escapeHtml(item.tone) + '">' + escapeHtml(item.category) + '</em><time>' + escapeHtml(formatTime(item.time)) + '</time></span>' +
      '<strong>' + escapeHtml(item.title) + '</strong><small>' + escapeHtml(item.description) + '</small></span>' +
      '<span class="factory-notification-item__chevron">' + icons.chevron + '</span></button>';
  }

  function resolveTarget(notification, data) {
    if (notification.targetPage === "task-detail" && data.tasks.some(function (item) { return item.id === notification.targetId; })) return true;
    if (notification.targetPage === "shipment-detail" && data.shipmentRecords.some(function (item) { return item.id === notification.targetId; })) return true;
    if (notification.targetPage === "repair-detail" && data.repairTasks.some(function (item) { return item.id === notification.targetId && !item.archived; })) return true;
    return false;
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

  function mount(app, reset) {
    var data = window.FactoryPrototypeData;
    var icons = window.FactoryIcons;
    if (reset) notificationState = { status: "all", visibleCount: 10 };

    function render() {
      var filtered = notificationState.status === "unread"
        ? data.notifications.filter(function (item) { return !item.read; })
        : data.notifications;
      var visible = filtered.slice(0, notificationState.visibleCount);
      var hasMore = visible.length < filtered.length;
      var emptyTitle = notificationState.status === "unread" ? "没有未读通知" : "暂无通知";
      var emptyDescription = notificationState.status === "unread"
        ? "新通知会在这里显示，进入对应详情后自动标记为已读。"
        : "新订单、新返修任务和业务处理结果会在这里显示。";

      app.innerHTML = '<div class="factory-notification-page">' +
        '<header class="detail-titlebar"><button type="button" class="back-button" id="notification-back-profile" aria-label="返回我的">' + icons.back + '</button><h1>通知中心</h1><div class="wechat-capsule" aria-hidden="true"><b>•••</b><i></i><span></span></div></header>' +
        '<main class="factory-notification-content"><div class="factory-notification-tabs" role="tablist" aria-label="通知状态">' +
          '<button type="button" class="' + (notificationState.status === "all" ? 'is-active' : '') + '" role="tab" aria-selected="' + (notificationState.status === "all") + '" data-notification-status="all">全部</button>' +
          '<button type="button" class="' + (notificationState.status === "unread" ? 'is-active' : '') + '" role="tab" aria-selected="' + (notificationState.status === "unread") + '" data-notification-status="unread">未读</button>' +
        '</div>' +
        (visible.length
          ? '<section class="factory-notification-list" aria-label="通知列表">' + visible.map(function (item) { return renderNotification(item, icons); }).join("") + '</section>' + (hasMore ? '<div class="factory-notification-more" data-notification-more>继续上滑加载</div>' : '<div class="factory-notification-end">已显示全部通知</div>')
          : '<section class="factory-notification-empty"><span>' + icons.bell + '</span><h2>' + emptyTitle + '</h2><p>' + emptyDescription + '</p></section>') +
        '</main></div><div class="prototype-toast" role="status"></div>';

      bindEvents();
    }

    function bindEvents() {
      document.querySelector("#notification-back-profile")?.addEventListener("click", function () { window.FactoryPages.profile.mount(app); });
      document.querySelectorAll("[data-notification-status]").forEach(function (button) {
        button.addEventListener("click", function () {
          notificationState.status = button.dataset.notificationStatus;
          notificationState.visibleCount = 10;
          render();
        });
      });
      document.querySelectorAll("[data-notification-id]").forEach(function (button) {
        button.addEventListener("click", function () {
          var notification = data.notifications.find(function (item) { return item.id === button.dataset.notificationId; });
          if (!notification || !resolveTarget(notification, data)) {
            showToast("目标记录暂不可用");
            return;
          }
          notification.read = true;
          window.FactoryPages[notification.targetPage].mount(app, notification.targetId, "notifications");
        });
      });
      var sentinel = document.querySelector("[data-notification-more]");
      if (sentinel && "IntersectionObserver" in window) {
        var observer = new IntersectionObserver(function (entries) {
          if (!entries.some(function (entry) { return entry.isIntersecting; })) return;
          observer.disconnect();
          notificationState.visibleCount += 10;
          render();
        }, { rootMargin: "120px" });
        observer.observe(sentinel);
      }
    }

    render();
  }

  window.FactoryPages ??= {};
  window.FactoryPages.notifications = { mount: mount };
})();
