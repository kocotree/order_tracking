import { factoryListData, peopleManagementData } from "../mock-data.js";
import { escapeHTML, showToast } from "../components/app-shell.js";
import { getNextSortState, renderSortableHeader, sortRows, updateSortHeaders } from "../components/table-sort.js";

const statusMeta = {
  pending: { label: "待审核", className: "is-warning" },
  approved: { label: "已通过", className: "is-success" },
  rejected: { label: "已拒绝", className: "is-danger" },
};

let adminApplications = peopleManagementData.adminApplications.map((item) => ({ ...item }));
let factoryApplications = peopleManagementData.factoryApplications.map((item) => ({ ...item }));
let users = peopleManagementData.users.map((item) => ({ ...item }));

function renderStatus(status) {
  const meta = statusMeta[status] ?? statusMeta.pending;
  return `<span class="status-badge ${meta.className}">${meta.label}</span>`;
}

function renderEmptyRow(colspan, message) {
  return `<tr><td colspan="${colspan}"><div class="people-empty-state">${escapeHTML(message)}</div></td></tr>`;
}

function renderAdminRows(rows) {
  if (rows.length === 0) return renderEmptyRow(5, "暂无管理员申请");
  return rows.map((item, index) => `
    <tr>
      <td class="people-sequence">${index + 1}</td>
      <td>${escapeHTML(item.name)}</td>
      <td>${escapeHTML(item.appliedAt)}</td>
      <td>${renderStatus(item.status)}</td>
      <td>${item.status === "pending" ? `<div class="people-row-actions"><button class="text-button" type="button" data-people-action="approve-admin" data-record-id="${escapeHTML(item.id)}">通过</button><button class="text-button people-danger-action" type="button" data-people-action="reject-admin" data-record-id="${escapeHTML(item.id)}">拒绝</button></div>` : "—"}</td>
    </tr>
  `).join("");
}

function renderFactoryApplicationRows(rows) {
  if (rows.length === 0) return renderEmptyRow(7, "暂无工厂用户申请");
  return rows.map((item, index) => `
    <tr>
      <td class="people-sequence">${index + 1}</td>
      <td>${escapeHTML(item.name)}</td>
      <td>${escapeHTML(item.position)}</td>
      <td>${escapeHTML(item.requestedFactoryName)}</td>
      <td>${escapeHTML(item.appliedAt)}</td>
      <td>${renderStatus(item.status)}</td>
      <td><button class="text-button" type="button" data-people-action="view-factory" data-record-id="${escapeHTML(item.id)}">详情</button></td>
    </tr>
  `).join("");
}

function renderRole(user) {
  const roleLabel = user.role === "admin" ? "管理员" : "工厂用户";
  return `${escapeHTML(roleLabel)}${user.isSuperAdmin ? `<span class="people-super-badge">最高权限</span>` : ""}`;
}

function canToggleUser(user) {
  return !user.isSuperAdmin && (peopleManagementData.currentUser.isSuperAdmin || user.role === "factory");
}

function renderUserRows(rows) {
  if (rows.length === 0) return renderEmptyRow(7, "该工厂暂无用户");
  return rows.map((user, index) => `
    <tr>
      <td class="people-sequence">${index + 1}</td>
      <td>${escapeHTML(user.name)}</td>
      <td><div class="people-role-cell">${renderRole(user)}</div></td>
      <td>${escapeHTML(user.position || "—")}</td>
      <td>${escapeHTML(user.factoryName || "—")}</td>
      <td><span class="status-badge ${user.enabled ? "is-success" : "is-neutral"}">${user.enabled ? "已启用" : "已停用"}</span></td>
      <td>${canToggleUser(user) ? `<button class="text-button${user.enabled ? " people-danger-action" : ""}" type="button" data-people-action="toggle-user" data-record-id="${escapeHTML(user.id)}">${user.enabled ? "停用" : "启用"}</button>` : "—"}</td>
    </tr>
  `).join("");
}

function applicationSortValue(item, key) {
  if (key === "status") return statusMeta[item.status]?.label ?? item.status;
  return item[key];
}

function userSortValue(user, key) {
  if (key === "role") return user.role === "admin" ? "管理员" : "工厂用户";
  if (key === "enabled") return user.enabled ? 1 : 0;
  return user[key];
}

function readFactoryFilter() {
  const query = window.location.hash.split("?")[1] ?? "";
  return new URLSearchParams(query).get("factory") ?? "";
}

function renderTabs(activeTab) {
  const tabs = [
    ...(peopleManagementData.currentUser.isSuperAdmin ? [{ id: "admin-applications", label: "管理员申请" }] : []),
    { id: "factory-applications", label: "工厂用户申请" },
    { id: "users", label: "用户列表" },
  ];
  return tabs.map((tab) => `<button class="people-tab${activeTab === tab.id ? " is-active" : ""}" type="button" role="tab" aria-selected="${String(activeTab === tab.id)}" data-people-tab="${tab.id}">${tab.label}</button>`).join("");
}

function renderUserToolbar(factoryFilter) {
  return `
    <div class="people-user-filter">
      <label for="people-factory-filter">所属工厂</label>
      <select id="people-factory-filter" data-people-factory-filter>
        <option value="">全部工厂</option>
        ${factoryListData.factories.map((factory) => `<option value="${escapeHTML(factory.id)}"${factory.id === factoryFilter ? " selected" : ""}>${escapeHTML(factory.factoryName)}</option>`).join("")}
      </select>
    </div>
  `;
}

function renderTable(activeTab, sortState, factoryFilter) {
  if (activeTab === "admin-applications") {
    const rows = sortRows(adminApplications, sortState, applicationSortValue);
    return `<table class="people-table people-admin-table data-grid-table"><thead><tr><th scope="col">序号</th>${renderSortableHeader("申请人", "name")}${renderSortableHeader("申请时间", "appliedAt")}${renderSortableHeader("申请状态", "status")}<th scope="col">操作</th></tr></thead><tbody>${renderAdminRows(rows)}</tbody></table>`;
  }

  if (activeTab === "factory-applications") {
    const rows = sortRows(factoryApplications, sortState, applicationSortValue);
    return `<table class="people-table people-factory-application-table data-grid-table"><thead><tr><th scope="col">序号</th>${renderSortableHeader("姓名", "name")}${renderSortableHeader("职位", "position")}${renderSortableHeader("申请工厂", "requestedFactoryName")}${renderSortableHeader("申请时间", "appliedAt")}${renderSortableHeader("申请状态", "status")}<th scope="col">操作</th></tr></thead><tbody>${renderFactoryApplicationRows(rows)}</tbody></table>`;
  }

  const filteredUsers = factoryFilter ? users.filter((user) => user.factoryId === factoryFilter) : users;
  const rows = sortRows(filteredUsers, sortState, userSortValue);
  return `<table class="people-table people-user-table data-grid-table"><thead><tr><th scope="col">序号</th>${renderSortableHeader("姓名", "name")}${renderSortableHeader("角色", "role")}${renderSortableHeader("职位", "position")}${renderSortableHeader("所属工厂", "factoryName")}${renderSortableHeader("启用状态", "enabled")}<th scope="col">操作</th></tr></thead><tbody>${renderUserRows(rows)}</tbody></table>`;
}

function renderFactoryApplicationDetailModal(record) {
  if (!record) return "";
  const factory = factoryListData.factories.find((item) => item.id === record.requestedFactoryId);
  const contacts = factory?.contacts ?? [];
  const contactNames = contacts.map((contact) => contact.name).filter(Boolean).join("、") || "—";
  const contactPhones = contacts.map((contact) => contact.phone).filter(Boolean).join("、") || "—";
  const reviewed = record.status !== "pending";

  return `
    <div class="people-modal-backdrop" data-people-modal-backdrop>
      <section class="people-modal people-application-detail-modal" role="dialog" aria-modal="true" aria-labelledby="people-modal-title">
        <header class="people-modal-header"><h2 id="people-modal-title">工厂用户申请详情</h2><button type="button" aria-label="关闭" data-close-people-modal>×</button></header>
        <div class="people-modal-body people-application-detail-body">
          <dl class="people-application-detail-grid">
            <div><dt>真实姓名</dt><dd>${escapeHTML(record.name)}</dd></div>
            <div><dt>联系电话</dt><dd><span class="people-phone-value">${escapeHTML(record.phone || "—")}${record.phoneVerified ? '<span class="people-verified-badge">已验证</span>' : ""}</span></dd></div>
            <div><dt>职位</dt><dd>${escapeHTML(record.position)}</dd></div>
            <div><dt>申请工厂</dt><dd>${escapeHTML(record.requestedFactoryName)}</dd></div>
            <div><dt>工厂联系人</dt><dd>${escapeHTML(contactNames)}</dd></div>
            <div><dt>工厂联系电话</dt><dd>${escapeHTML(contactPhones)}</dd></div>
            <div><dt>申请时间</dt><dd>${escapeHTML(record.appliedAt)}</dd></div>
            <div><dt>申请状态</dt><dd>${renderStatus(record.status)}</dd></div>
            ${reviewed ? `<div><dt>审核人</dt><dd>${escapeHTML(record.reviewedBy || "—")}</dd></div><div><dt>审核时间</dt><dd>${escapeHTML(record.reviewedAt || "—")}</dd></div>` : ""}
            ${record.status === "rejected" ? `<div class="people-detail-wide"><dt>拒绝原因</dt><dd>${escapeHTML(record.rejectReason || "—")}</dd></div>` : ""}
          </dl>
        </div>
        <footer class="people-modal-actions">
          <button class="order-secondary-button" type="button" data-close-people-modal>关闭</button>
          ${record.status === "pending" ? `<button class="order-secondary-button people-reject-button" type="button" data-detail-decision="reject-factory" data-record-id="${escapeHTML(record.id)}">拒绝</button><button class="order-primary-button" type="button" data-detail-decision="approve-factory" data-record-id="${escapeHTML(record.id)}">通过</button>` : ""}
        </footer>
      </section>
    </div>
  `;
}

function renderActionModal(modal) {
  if (!modal) return "";
  if (modal.action === "view-factory") {
    return renderFactoryApplicationDetailModal(factoryApplications.find((item) => item.id === modal.id));
  }
  const isFactoryApproval = modal.action === "approve-factory";
  const isToggle = modal.action === "toggle-user";
  const record = modal.action.includes("admin")
    ? adminApplications.find((item) => item.id === modal.id)
    : modal.action.includes("factory")
      ? factoryApplications.find((item) => item.id === modal.id)
      : users.find((item) => item.id === modal.id);
  const isReject = modal.action.startsWith("reject");
  const title = isToggle
    ? `${record?.enabled ? "停用" : "启用"}用户`
    : `${isReject ? "拒绝" : "通过"}${modal.action.includes("admin") ? "管理员" : "工厂用户"}申请`;
  const description = isToggle
    ? `确认${record?.enabled ? "停用" : "启用"}“${record?.name ?? "该用户"}”吗？`
    : isReject
      ? `确认拒绝“${record?.name ?? "该申请人"}”的申请吗？拒绝记录将继续保留。`
      : modal.action === "approve-admin"
        ? `通过后，“${record?.name ?? "该申请人"}”将获得普通管理员角色。`
        : `通过后，“${record?.name ?? "该申请人"}”将绑定到所选工厂并进入用户列表。`;

  return `
    <div class="people-modal-backdrop" data-people-modal-backdrop>
      <section class="people-modal" role="dialog" aria-modal="true" aria-labelledby="people-modal-title">
        <form data-people-action-form data-action="${escapeHTML(modal.action)}" data-record-id="${escapeHTML(modal.id)}">
          <header class="people-modal-header"><h2 id="people-modal-title">${escapeHTML(title)}</h2><button type="button" aria-label="关闭" data-close-people-modal>×</button></header>
          <div class="people-modal-body">
            <p>${escapeHTML(description)}</p>
            ${isFactoryApproval ? `<label class="people-bind-field"><span>绑定工厂</span><select name="factoryId">${factoryListData.factories.map((factory) => `<option value="${escapeHTML(factory.id)}"${factory.id === record?.requestedFactoryId ? " selected" : ""}>${escapeHTML(factory.factoryName)}</option>`).join("")}</select></label>` : ""}
            ${modal.action === "reject-factory" ? `<label class="people-reject-field"><span>拒绝原因</span><textarea name="rejectReason" rows="3" placeholder="请输入拒绝原因" required></textarea></label>` : ""}
          </div>
          <footer class="people-modal-actions"><button class="order-secondary-button" type="button" data-close-people-modal>取消</button><button class="order-primary-button${isReject || (isToggle && record?.enabled) ? " is-danger" : ""}" type="submit">确认${isToggle ? (record?.enabled ? "停用" : "启用") : isReject ? "拒绝" : "通过"}</button></footer>
        </form>
      </section>
    </div>
  `;
}

export function renderPeopleManagementPage() {
  return `
    <article class="people-management-page" data-people-management-page>
      <section class="section-card people-management-card" aria-labelledby="people-management-title">
        <header class="people-management-header"><h1 id="people-management-title">人员管理</h1></header>
        <nav class="people-tabs" role="tablist" aria-label="人员管理分类" data-people-tabs></nav>
        <div class="people-toolbar" data-people-toolbar></div>
        <div class="table-scroll people-table-scroll" data-people-table-root></div>
      </section>
      <div data-people-modal-root></div>
    </article>
  `;
}

export function bindPeopleManagementPage() {
  const page = document.querySelector("[data-people-management-page]");
  if (!page) return;

  const tabsRoot = page.querySelector("[data-people-tabs]");
  const toolbarRoot = page.querySelector("[data-people-toolbar]");
  const tableRoot = page.querySelector("[data-people-table-root]");
  const modalRoot = page.querySelector("[data-people-modal-root]");
  let factoryFilter = readFactoryFilter();
  let activeTab = factoryFilter ? "users" : peopleManagementData.currentUser.isSuperAdmin ? "admin-applications" : "factory-applications";
  let modal = null;
  const sortStates = {
    "admin-applications": { key: null, direction: "asc" },
    "factory-applications": { key: null, direction: "asc" },
    users: { key: null, direction: "asc" },
  };

  const renderPage = () => {
    tabsRoot.innerHTML = renderTabs(activeTab);
    toolbarRoot.innerHTML = activeTab === "users" ? renderUserToolbar(factoryFilter) : "";
    toolbarRoot.hidden = activeTab !== "users";
    tableRoot.innerHTML = renderTable(activeTab, sortStates[activeTab], factoryFilter);
    updateSortHeaders(tableRoot, sortStates[activeTab]);
    modalRoot.innerHTML = renderActionModal(modal);
  };

  const closeModal = () => {
    modal = null;
    renderPage();
  };

  page.addEventListener("click", (event) => {
    const nextSortState = getNextSortState(event, sortStates[activeTab]);
    if (nextSortState) {
      sortStates[activeTab] = nextSortState;
      renderPage();
      return;
    }

    const tab = event.target.closest("[data-people-tab]")?.dataset.peopleTab;
    if (tab) {
      activeTab = tab;
      modal = null;
      renderPage();
      return;
    }

    const actionButton = event.target.closest("[data-people-action]");
    if (actionButton) {
      modal = { action: actionButton.dataset.peopleAction, id: actionButton.dataset.recordId };
      renderPage();
      return;
    }

    const detailDecisionButton = event.target.closest("[data-detail-decision]");
    if (detailDecisionButton) {
      modal = { action: detailDecisionButton.dataset.detailDecision, id: detailDecisionButton.dataset.recordId };
      renderPage();
      return;
    }

    if (event.target.closest("[data-close-people-modal]") || event.target.matches("[data-people-modal-backdrop]")) {
      closeModal();
    }
  });

  page.addEventListener("change", (event) => {
    if (!event.target.matches("[data-people-factory-filter]")) return;
    factoryFilter = event.target.value;
    const nextHash = factoryFilter ? `#/people?factory=${encodeURIComponent(factoryFilter)}` : "#/people";
    window.history.replaceState(null, "", nextHash);
    renderPage();
  });

  page.addEventListener("submit", (event) => {
    const form = event.target.closest("[data-people-action-form]");
    if (!form) return;
    event.preventDefault();
    const action = form.dataset.action;
    const id = form.dataset.recordId;
    let toastMessage = "人员状态已更新。";

    if (action === "approve-admin" || action === "reject-admin") {
      const approved = action === "approve-admin";
      const application = adminApplications.find((item) => item.id === id);
      adminApplications = adminApplications.map((item) => item.id === id ? { ...item, status: approved ? "approved" : "rejected" } : item);
      if (approved && application && !users.some((user) => user.name === application.name && user.role === "admin")) {
        users = [...users, { id: `user-admin-${Date.now()}`, name: application.name, role: "admin", position: "跟单人员", factoryId: "", factoryName: "—", enabled: true, isSuperAdmin: false }];
      }
      toastMessage = approved ? `${application?.name ?? "申请人"}已成为普通管理员。` : `${application?.name ?? "申请人"}的管理员申请已拒绝。`;
    }

    if (action === "approve-factory" || action === "reject-factory") {
      const approved = action === "approve-factory";
      const application = factoryApplications.find((item) => item.id === id);
      const formData = new FormData(form);
      const rejectReason = String(formData.get("rejectReason") ?? "").trim();
      if (!approved && !rejectReason) {
        showToast("无法拒绝", "请填写拒绝原因。");
        return;
      }
      const factoryId = approved ? String(formData.get("factoryId") ?? "") : application?.requestedFactoryId ?? "";
      const factory = factoryListData.factories.find((item) => item.id === factoryId);
      const reviewedAt = new Intl.DateTimeFormat("zh-CN", { year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false }).format(new Date()).replaceAll("/", "-");
      factoryApplications = factoryApplications.map((item) => item.id === id ? {
        ...item,
        status: approved ? "approved" : "rejected",
        requestedFactoryId: factoryId || item.requestedFactoryId,
        requestedFactoryName: factory?.factoryName ?? item.requestedFactoryName,
        reviewedBy: peopleManagementData.currentUser.name,
        reviewedAt,
        rejectReason: approved ? "" : rejectReason,
      } : item);
      if (approved && application && factory && !users.some((user) => user.name === application.name && user.role === "factory")) {
        users = [...users, { id: `user-factory-${Date.now()}`, name: application.name, phone: application.phone, phoneVerified: application.phoneVerified, role: "factory", position: application.position, factoryId: factory.id, factoryName: factory.factoryName, enabled: true, isSuperAdmin: false }];
      }
      toastMessage = approved ? `${application?.name ?? "申请人"}已绑定${factory?.factoryName ?? "所选工厂"}。` : `${application?.name ?? "申请人"}的工厂用户申请已拒绝。`;
    }

    if (action === "toggle-user") {
      const user = users.find((item) => item.id === id);
      users = users.map((item) => item.id === id ? { ...item, enabled: !item.enabled } : item);
      toastMessage = `${user?.name ?? "该用户"}已${user?.enabled ? "停用" : "启用"}。`;
    }

    modal = null;
    renderPage();
    showToast("操作成功", toastMessage);
  });

  page.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && modal) closeModal();
  });

  renderPage();
}
