import { factoryListData, peopleManagementData } from "../mock-data.js";
import { escapeHTML } from "../components/app-shell.js";
import { getNextSortState, renderSortableHeader, sortRows, updateSortHeaders } from "../components/table-sort.js";
import { renderNumberPagination } from "../components/pagination.js";

const applications = peopleManagementData.factoryApplications;
const users = peopleManagementData.users;
const statusLabels = { pending: "待审核", approved: "已通过", rejected: "已拒绝" };
const phone = value => String(value || "—").replace(/^(\d{3})\d{4}(\d{4})$/, "$1****$2");
const enabledBadge = user => `<span class="status-badge ${user.enabled ? "is-approved" : "is-disabled"}">${user.enabled ? "已启用" : "已停用"}</span>`;
const action = user => user.isSuperAdmin ? "—" : `<button class="text-button ${user.enabled ? "danger" : ""}" type="button" data-toggle-user="${escapeHTML(user.id)}">${user.enabled ? "停用" : "启用"}</button>`;

export function renderPeopleManagementPage() {
  return `<article class="people-management-page" data-people-management-page>
    <section class="section-card people-management-filter-card"><nav class="people-tabs" aria-label="人员管理分类" data-people-tabs></nav><div class="people-toolbar" data-people-toolbar></div></section>
    <section class="section-card people-management-card"><header class="people-management-header"><h1>人员管理</h1></header><div class="people-table-scroll" data-people-table-root></div><footer class="order-list-footer"><span>每页展示 10 条。</span><nav class="order-pagination" aria-label="人员列表分页" data-people-pagination></nav></footer></section>
    <div data-people-modal-root></div>
  </article>`;
}

export function bindPeopleManagementPage() {
  const root = document.querySelector("[data-people-management-page]");
  const query = new URLSearchParams(window.location.hash.split("?")[1] || "");
  let factory = query.get("factory") || "";
  let tab = query.get("tab") || (factory ? "users" : "factory-applications");
  if (tab === "admin-users" && !peopleManagementData.currentUser.isSuperAdmin) tab = "factory-applications";
  let status = "", page = 1, sort = { key: null, direction: "asc" };
  let selected = null, target = null, decision = "", boundFactory = "", reason = "", error = "";
  const modalRoot = root.querySelector("[data-people-modal-root]");
  const renderModal = () => {
    if (target) {
      modalRoot.innerHTML = `<div class="modal-backdrop" data-people-backdrop><section class="modal" role="dialog" aria-modal="true"><header><h2>${target.enabled ? "停用" : "启用"}${target.role === "admin" ? "管理员" : "用户"}</h2><button type="button" aria-label="关闭" data-close-people-modal>×</button></header><div class="modal-body"><p>确认${target.enabled ? "停用" : "启用"}“${escapeHTML(target.name)}”吗？</p></div><footer><button class="secondary-button" type="button" data-close-people-modal>取消</button><button class="primary-button" type="button" data-toggle-confirm>确认</button></footer></section></div>`;
      return;
    }
    if (!selected) { modalRoot.innerHTML = ""; return; }
    const contacts = factoryListData.factories.find(item => item.id === selected.requestedFactoryId)?.contacts || [];
    const fields = [["真实姓名", selected.name], ["验证联系电话", phone(selected.phone)], ["职位", selected.position], ["申请工厂", selected.requestedFactoryName], ["申请时间", selected.appliedAt], ["申请状态", statusLabels[selected.status]]];
    if (selected.reviewedAt) fields.push(["审核时间", selected.reviewedAt]);
    if (selected.rejectReason) fields.push(["拒绝原因", selected.rejectReason]);
    modalRoot.innerHTML = `<div class="modal-backdrop" data-people-backdrop><section class="modal application-detail" role="dialog" aria-modal="true"><header><h2>工厂用户申请详情</h2><button type="button" aria-label="关闭" data-close-people-modal>×</button></header><div class="modal-body"><dl class="detail-grid">${fields.map(([label,value]) => `<div><dt>${label}</dt><dd>${escapeHTML(value)}</dd></div>`).join("")}</dl><section class="contact-summary"><h3>工厂联系人</h3>${contacts.length ? contacts.map(item => `<p>${escapeHTML(item.name)}　${escapeHTML(item.phone)}</p>`).join("") : "<p>暂无联系人</p>"}</section>
    ${decision === "approve" ? `<label class="decision-field">绑定工厂<select data-binding-factory>${factoryListData.factories.map(item => `<option value="${escapeHTML(item.id)}" ${item.id === boundFactory ? "selected" : ""}>${escapeHTML(item.supplierNumber)}　${escapeHTML(item.factoryName)}</option>`).join("")}</select></label>` : ""}
    ${decision === "reject" ? `<label class="decision-field">拒绝原因<textarea data-rejection-reason maxlength="500" placeholder="请填写拒绝原因">${escapeHTML(reason)}</textarea></label>` : ""}
    ${error ? `<p class="page-error">${escapeHTML(error)}</p>` : ""}</div><footer>${decision ? '<button class="secondary-button" type="button" data-decision-back>返回</button><button class="primary-button" type="button" data-decision-confirm>确认</button>' : selected.status === "pending" ? '<button class="secondary-button danger-outline" type="button" data-decision="reject">拒绝</button><button class="primary-button" type="button" data-decision="approve">通过</button>' : '<button class="secondary-button" type="button" data-close-people-modal>关闭</button>'}</footer></section></div>`;
  };
  const render = () => {
    const tabs = [...(peopleManagementData.currentUser.isSuperAdmin ? [["admin-users", "管理员"]] : []), ["factory-applications", "工厂用户申请"], ["users", "工厂用户列表"]];
    root.querySelector("[data-people-tabs]").innerHTML = tabs.map(([key, label]) => `<a href="#/people?tab=${key}" class="${tab === key ? "router-link-active" : ""}" data-people-tab="${key}">${label}</a>`).join("");
    const toolbar = root.querySelector("[data-people-toolbar]");
    toolbar.hidden = tab === "admin-users";
    toolbar.innerHTML = tab === "users" ? `<label class="people-user-filter"><span>所属工厂</span><select data-factory-filter><option value="">全部工厂</option>${factoryListData.factories.map(item => `<option value="${escapeHTML(item.id)}" ${item.id === factory ? "selected" : ""}>${escapeHTML(item.factoryName)}</option>`).join("")}</select></label>` : `<label class="people-user-filter"><span>申请状态</span><select data-application-filter><option value="">全部状态</option>${Object.entries(statusLabels).map(([key,label]) => `<option value="${key}" ${key === status ? "selected" : ""}>${label}</option>`).join("")}</select></label>`;
    const isApplication = tab === "factory-applications", isAdmin = tab === "admin-users";
    const filtered = isApplication ? applications.filter(item => !status || item.status === status) : users.filter(item => item.role === (isAdmin ? "admin" : "factory") && (isAdmin || !factory || item.factoryId === factory));
    const rows = sortRows(filtered, sort, (item,key) => key === "phone" ? phone(item.phone) : key === "status" ? statusLabels[item.status] : item[key]);
    page = Math.min(page, Math.max(1, Math.ceil(rows.length / 10)));
    const columns = isApplication ? [["姓名","name"],["职位","position"],["申请工厂","requestedFactoryName"],["申请时间","appliedAt"],["申请状态","status"]] : isAdmin ? [["姓名","name"],["角色","role"],["手机号","phone"],["启用状态","enabled"]] : [["姓名","name"],["角色","role"],["职位","position"],["所属工厂","factoryName"],["启用状态","enabled"]];
    const body = rows.slice((page - 1) * 10, page * 10).map((item,index) => `<tr><td>${(page - 1) * 10 + index + 1}</td><td>${escapeHTML(item.name)}</td>${isApplication ? `<td>${escapeHTML(item.position)}</td><td>${escapeHTML(item.requestedFactoryName)}</td><td>${escapeHTML(item.appliedAt)}</td><td><span class="status-badge is-${item.status}">${statusLabels[item.status]}</span></td><td><button class="text-button" data-application-detail="${escapeHTML(item.id)}" type="button">详情</button></td>` : isAdmin ? `<td>管理员 ${item.isSuperAdmin ? '<span class="super-badge">最高权限</span>' : ""}</td><td>${phone(item.phone)}</td><td>${enabledBadge(item)}</td><td>${action(item)}</td>` : `<td>工厂用户</td><td>${escapeHTML(item.position || "—")}</td><td>${escapeHTML(item.factoryName || "—")}</td><td>${enabledBadge(item)}</td><td>${action(item)}</td>`}</tr>`).join("");
    const tableRoot = root.querySelector("[data-people-table-root]");
    tableRoot.innerHTML = `<table class="people-table data-grid-table ${isApplication ? "people-factory-application-table" : "people-user-table"}"><thead><tr><th>序号</th>${columns.map(([label,key]) => renderSortableHeader(label,key)).join("")}<th>操作</th></tr></thead><tbody>${body || `<tr><td class="empty-cell" colspan="${columns.length + 2}">${isApplication ? "暂无工厂用户申请" : isAdmin ? "暂无管理员账号" : "暂无工厂用户"}</td></tr>`}</tbody></table>`;
    updateSortHeaders(tableRoot, sort);
    root.querySelector("[data-people-pagination]").innerHTML = renderNumberPagination(page, rows.length, "data-people-page");
    renderModal();
  };
  const close = () => { selected = target = null; decision = reason = error = ""; renderModal(); };
  root.addEventListener("click", event => {
    const nextSort = getNextSortState(event, sort);
    if (nextSort) { sort = nextSort; page = 1; render(); return; }
    const tabButton = event.target.closest("[data-people-tab]");
    if (tabButton) { event.preventDefault(); tab = tabButton.dataset.peopleTab; page = 1; sort = { key: null, direction: "asc" }; close(); window.history.replaceState(null, "", `#/people?tab=${tab}`); render(); return; }
    const pager = event.target.closest("[data-people-page], [data-people-page-action]");
    if (pager && !pager.disabled) { page = pager.dataset.peoplePage ? Number(pager.dataset.peoplePage) : page + (pager.dataset.peoplePageAction === "next" ? 1 : -1); render(); return; }
    const applicationId = event.target.closest("[data-application-detail]")?.dataset.applicationDetail;
    if (applicationId) { selected = applications.find(item => item.id === applicationId); boundFactory = selected.requestedFactoryId; decision = reason = error = ""; renderModal(); return; }
    const userId = event.target.closest("[data-toggle-user]")?.dataset.toggleUser;
    if (userId) { target = users.find(item => item.id === userId); renderModal(); return; }
    if (event.target.closest("[data-toggle-confirm]")) { if (target && !target.isSuperAdmin) target.enabled = !target.enabled; close(); render(); return; }
    const choice = event.target.closest("[data-decision]")?.dataset.decision;
    if (choice) { decision = choice; renderModal(); return; }
    if (event.target.closest("[data-decision-back]")) { decision = error = ""; renderModal(); return; }
    if (event.target.closest("[data-decision-confirm]")) {
      if (decision === "reject" && !reason.trim()) { error = "请填写拒绝原因"; renderModal(); return; }
      const binding = factoryListData.factories.find(item => item.id === boundFactory);
      if (decision === "approve" && !binding) { error = "请选择绑定工厂"; renderModal(); return; }
      selected.status = decision === "approve" ? "approved" : "rejected";
      selected.rejectReason = decision === "reject" ? reason.trim() : "";
      selected.reviewedAt = new Date().toLocaleString("zh-CN", { hour12: false });
      if (binding && decision === "approve") users.push({ id: `demo-${selected.id}`, name: selected.name, role: "factory", position: selected.position, phone: selected.phone, factoryId: binding.id, factoryName: binding.factoryName, enabled: true, isSuperAdmin: false });
      close(); render(); return;
    }
    if (event.target.closest("[data-close-people-modal]") || event.target.matches("[data-people-backdrop]")) close();
  });
  root.addEventListener("change", event => {
    if (event.target.matches("[data-factory-filter]")) { factory = event.target.value; page = 1; render(); }
    if (event.target.matches("[data-application-filter]")) { status = event.target.value; page = 1; render(); }
    if (event.target.matches("[data-binding-factory]")) boundFactory = event.target.value;
  });
  root.addEventListener("input", event => { if (event.target.matches("[data-rejection-reason]")) reason = event.target.value; });
  render();
}
