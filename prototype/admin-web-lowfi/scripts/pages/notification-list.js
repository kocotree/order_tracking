import { notificationData } from "../mock-data.js";
import { escapeHTML } from "../components/app-shell.js";
import { buildRouteWithReturn, getReturnRoute } from "../router.js";

export function renderNotificationListPage() {
  return `<article class="notifications-page" data-notification-record-page><section class="section-card notifications-card">
    <header class="notifications-header"><button class="detail-back-button notifications-back-button" type="button" data-notification-back aria-label="返回上一页"><svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="m15 18-6-6 6-6" /></svg>返回</button>
      <nav class="notification-tabs" aria-label="通知筛选"><button type="button" data-notification-status="all">全部</button><button type="button" data-notification-status="unread">未读</button></nav></header>
    <div class="notification-list" data-notification-record-list></div><footer class="notification-pagination" data-notification-pagination></footer>
  </section></article>`;
}
export function bindNotificationListPage() {
  const root = document.querySelector("[data-notification-record-page]");
  const params = new URLSearchParams(window.location.hash.split("?")[1] || "");
  let status = params.get("status") === "unread" ? "unread" : "all";
  let page = Math.max(Number(params.get("page")) || 1, 1);
  const category = value => ({ "正常发货":"发货", "质检返修":"返修", "合同出货提醒":"合同出货" }[value] || value);
  const render = () => {
    const rows = [...notificationData].filter(item => status === "all" || !item.read).sort((a,b) => b.time.localeCompare(a.time));
    const pages = Math.max(1, Math.ceil(rows.length / 10));
    page = Math.min(page, pages);
    root.querySelectorAll("[data-notification-status]").forEach(button => button.classList.toggle("is-active", button.dataset.notificationStatus === status));
    root.querySelector("[data-notification-record-list]").innerHTML = rows.length ? rows.slice((page - 1) * 10, page * 10).map(item => `<button class="notification-list-item${item.read ? "" : " is-unread"}" type="button" data-notification-record="${escapeHTML(item.id)}"><i class="notification-unread-dot${item.read ? " is-read" : ""}" aria-label="${item.read ? "已读" : "未读"}"></i><span class="notification-category">${escapeHTML(category(item.category))}</span><span class="notification-copy"><strong>${escapeHTML(item.title)}</strong><span>${escapeHTML(item.description)}</span></span><time>${escapeHTML(item.time)}</time></button>`).join("") : '<div class="notification-empty">暂无通知</div>';
    const footer = root.querySelector("[data-notification-pagination]");
    footer.hidden = pages <= 1;
    footer.innerHTML = `<button type="button" data-notification-page="-1" ${page <= 1 ? "disabled" : ""}>上一页</button><span>${page} / ${pages}</span><button type="button" data-notification-page="1" ${page >= pages ? "disabled" : ""}>下一页</button>`;
  };
  const sync = () => { window.history.replaceState(null, "", `#/notifications?status=${status}&page=${page}`); render(); };
  root.addEventListener("click", event => {
    if (event.target.closest("[data-notification-back]")) { window.location.hash = getReturnRoute("/dashboard"); return; }
    const tab = event.target.closest("[data-notification-status]");
    if (tab) { status = tab.dataset.notificationStatus; page = 1; sync(); return; }
    const pager = event.target.closest("[data-notification-page]");
    if (pager && !pager.disabled) { page += Number(pager.dataset.notificationPage); sync(); return; }
    const target = event.target.closest("[data-notification-record]");
    const item = notificationData.find(item => item.id === target?.dataset.notificationRecord);
    if (item) { item.read = true; window.location.hash = buildRouteWithReturn(item.route, `/notifications?status=${status}&page=${page}`); }
  });
  render();
}
