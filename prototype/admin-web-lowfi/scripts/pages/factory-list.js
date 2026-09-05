import { factoryListData } from "../mock-data.js";
import { escapeHTML, showToast } from "../components/app-shell.js";
import { getNextSortState, renderSortableHeader, sortRows, updateSortHeaders } from "../components/table-sort.js";

const searchIcon = `<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><circle cx="11" cy="11" r="6.5" stroke="currentColor" stroke-width="1.7"/><path d="m16 16 4 4" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/></svg>`;
const requiredContractFields = [
  ["factoryCode", "工厂代码"],
  ["legalName", "单位全称"],
  ["address", "单位地址"],
  ["legalRepresentative", "法定代表人"],
];

function cloneFactory(factory) {
  return {
    ...factory,
    contacts: (factory.contacts ?? []).map((contact) => ({ ...contact })),
    sourceAliases: [...(factory.sourceAliases ?? [])],
  };
}

let factoryRecords = factoryListData.factories.map(cloneFactory);

function normalize(value) {
  return String(value ?? "").trim().toLocaleLowerCase("zh-CN");
}

function missingContractFields(factory) {
  return requiredContractFields.filter(([key]) => !String(factory[key] ?? "").trim()).map(([, label]) => label);
}

function fieldValue(value) {
  return escapeHTML(value ?? "");
}

function renderContacts(factory, key) {
  const values = (factory.contacts ?? []).map((contact) => contact[key]).filter(Boolean);
  return values.length ? values.map(escapeHTML).join("、") : `<span class="factory-empty-value">—</span>`;
}

function renderContractStatus(factory) {
  const missing = missingContractFields(factory);
  return missing.length === 0
    ? `<span class="factory-contract-badge is-complete">完整</span>`
    : `<span class="factory-contract-badge is-incomplete" title="缺少：${escapeHTML(missing.join("、"))}">待补充 ${missing.length} 项</span>`;
}

function factorySortValue(factory, key) {
  if (key === "contactName") return (factory.contacts ?? []).map((contact) => contact.name).filter(Boolean).join("、");
  if (key === "contactPhone") return (factory.contacts ?? []).map((contact) => contact.phone).filter(Boolean).join("、");
  if (key === "contractStatus") return missingContractFields(factory).length;
  return factory[key];
}

function renderContactEditorRows(contacts = []) {
  const rows = contacts.length ? contacts : [{ name: "", phone: "" }];
  return rows.map((contact) => `
    <div class="factory-contact-row" data-contact-row>
      <span class="factory-form-label"><span>联系人</span></span>
      <div class="factory-form-control"><input type="text" aria-label="联系人" value="${fieldValue(contact.name)}" placeholder="姓名" data-contact-name /></div>
      <span class="factory-form-label"><span>联系电话</span></span>
      <div class="factory-form-control"><input type="tel" aria-label="联系电话" value="${fieldValue(contact.phone)}" placeholder="手机或座机" data-contact-phone /></div>
    </div>
  `).join("");
}

function renderEditor(factory = {}, mode = "edit") {
  const title = mode === "add" ? "新增工厂" : "编辑";
  const fixedFieldAttribute = mode === "edit" ? " readonly aria-readonly=\"true\"" : "";
  return `
    <div class="factory-modal-backdrop" data-factory-modal-backdrop>
      <section class="factory-modal" role="dialog" aria-modal="true" aria-labelledby="factory-editor-title">
        <form class="factory-editor-panel" data-factory-editor data-editor-mode="${mode}" data-factory-id="${escapeHTML(factory.id ?? "")}">
          <header class="factory-editor-header">
            <h2 id="factory-editor-title">${title}</h2>
            <button class="factory-modal-close" type="button" data-cancel-factory aria-label="关闭编辑弹窗">×</button>
          </header>

          <div class="factory-editor-body">
            <section class="factory-editor-section">
              <h3 class="sr-only">基础及合同资料</h3>
              <div class="factory-form-grid factory-main-form">
                <label class="factory-form-label" for="supplier-number"><span>编号</span></label>
                <div class="factory-form-control"><input id="supplier-number" type="text" name="supplierNumber" value="${fieldValue(factory.supplierNumber)}" placeholder="例如 A10" required${fixedFieldAttribute} /></div>
                <label class="factory-form-label" for="factory-code"><span>工厂代码</span></label>
                <div class="factory-form-control"><input id="factory-code" type="text" name="factoryCode" value="${fieldValue(factory.factoryCode)}" placeholder="例如 XZ，可留空" /></div>

                <label class="factory-form-label" for="factory-name"><span>工厂名称</span></label>
                <div class="factory-form-control"><input id="factory-name" type="text" name="factoryName" value="${fieldValue(factory.factoryName)}" placeholder="日常使用的工厂简称" required${fixedFieldAttribute} /></div>
                <label class="factory-form-label" for="factory-legal-representative"><span>法定代表人</span></label>
                <div class="factory-form-control"><input id="factory-legal-representative" type="text" name="legalRepresentative" value="${fieldValue(factory.legalRepresentative)}"${fixedFieldAttribute} /></div>

                <label class="factory-form-label" for="factory-legal-name"><span>单位全称</span></label>
                <div class="factory-form-control is-wide"><input id="factory-legal-name" type="text" name="legalName" value="${fieldValue(factory.legalName)}" placeholder="营业执照上的单位名称"${fixedFieldAttribute} /></div>

                ${renderContactEditorRows(factory.contacts)}

                <label class="factory-form-label" for="factory-address"><span>单位地址</span></label>
                <div class="factory-form-control is-wide"><input id="factory-address" type="text" name="address" value="${fieldValue(factory.address)}" /></div>
              </div>
            </section>
          </div>

          <footer class="factory-editor-actions">
            <button class="order-secondary-button" type="button" data-cancel-factory>取消</button>
            <button class="order-primary-button" type="submit">保存</button>
          </footer>
        </form>
      </section>
    </div>
  `;
}

function renderDetailValue(value) {
  return String(value ?? "").trim() ? escapeHTML(value) : `<span class="factory-empty-value">—</span>`;
}

function renderFactoryDetail(factory) {
  return `
    <div class="factory-modal-backdrop" data-factory-modal-backdrop>
      <section class="factory-modal factory-detail-modal" role="dialog" aria-modal="true" aria-labelledby="factory-detail-title">
        <div class="factory-editor-panel">
          <header class="factory-editor-header">
            <h2 id="factory-detail-title">详情</h2>
            <button class="factory-modal-close" type="button" data-cancel-factory aria-label="关闭详情弹窗">×</button>
          </header>
          <div class="factory-detail-body">
            <div class="factory-detail-grid">
              <div class="factory-detail-label">编号</div>
              <div class="factory-detail-value">${renderDetailValue(factory.supplierNumber)}</div>
              <div class="factory-detail-label">工厂代码</div>
              <div class="factory-detail-value">${renderDetailValue(factory.factoryCode)}</div>

              <div class="factory-detail-label">工厂名称</div>
              <div class="factory-detail-value">${renderDetailValue(factory.factoryName)}</div>
              <div class="factory-detail-label">法定代表人</div>
              <div class="factory-detail-value">${renderDetailValue(factory.legalRepresentative)}</div>

              <div class="factory-detail-label">单位全称</div>
              <div class="factory-detail-value is-wide">${renderDetailValue(factory.legalName)}</div>

              <div class="factory-detail-label">联系人</div>
              <div class="factory-detail-value">${renderContacts(factory, "name")}</div>
              <div class="factory-detail-label">联系电话</div>
              <div class="factory-detail-value">${renderContacts(factory, "phone")}</div>

              <div class="factory-detail-label">单位地址</div>
              <div class="factory-detail-value is-wide">${renderDetailValue(factory.address)}</div>
            </div>
          </div>
        </div>
      </section>
    </div>
  `;
}

function renderRows(factories, rowStart) {
  if (factories.length === 0) {
    return `<tr><td colspan="9"><div class="empty-state"><div><span class="empty-state-mark">0</span><strong>没有符合条件的工厂</strong><p>可以更换关键词或筛选条件后重新搜索。</p></div></div></td></tr>`;
  }

  const rows = factories.map((factory, index) => {
    const row = `
      <tr class="factory-data-row">
        <td class="factory-sequence">${rowStart + index + 1}</td>
        <td class="factory-supplier-number">${escapeHTML(factory.supplierNumber || "—")}</td>
        <td><strong class="factory-name">${escapeHTML(factory.factoryName)}</strong></td>
        <td class="factory-legal-name">${factory.legalName ? escapeHTML(factory.legalName) : `<span class="factory-empty-value">—</span>`}</td>
        <td>${renderContacts(factory, "name")}</td>
        <td class="factory-phone">${renderContacts(factory, "phone")}</td>
        <td>${renderContractStatus(factory)}</td>
        <td><button class="factory-user-count" type="button" data-view-factory-users="${escapeHTML(factory.id)}">${factory.connectedUsers} 人</button></td>
        <td><div class="factory-row-actions"><button class="text-button" type="button" data-view-factory="${escapeHTML(factory.id)}">详情</button><button class="text-button" type="button" data-edit-factory="${escapeHTML(factory.id)}">编辑</button></div></td>
      </tr>
    `;
    return row;
  }).join("");

  return rows;
}

function renderPagination(currentPage, totalPages, totalItems) {
  if (totalItems === 0) return `<span class="order-page-total">共 0 条</span>`;
  const pages = Array.from({ length: totalPages }, (_, index) => {
    const page = index + 1;
    return `<button class="order-page-button${page === currentPage ? " is-current" : ""}" type="button" aria-label="第 ${page} 页" aria-current="${page === currentPage ? "page" : "false"}" data-factory-page="${page}">${page}</button>`;
  }).join("");
  return `<span class="order-page-total">共 ${totalItems} 条</span><button class="order-page-button order-page-arrow" type="button" aria-label="上一页" data-factory-page-action="prev" ${currentPage === 1 ? "disabled" : ""}>‹</button>${pages}<button class="order-page-button order-page-arrow" type="button" aria-label="下一页" data-factory-page-action="next" ${currentPage === totalPages ? "disabled" : ""}>›</button>`;
}

export function renderFactoryListPage() {
  return `
    <article class="factory-list-page" data-factory-list-page>
      <section class="order-list-filter-card factory-filter-card" aria-label="工厂筛选">
        <form class="order-filter-form" data-factory-filter-form>
          <div class="order-filter-row">
            <label class="order-list-search-field factory-search-field"><span class="sr-only">搜索工厂资料</span>${searchIcon}<input type="search" placeholder="搜索工厂名称、单位全称、联系人或电话" autocomplete="off" data-factory-keyword /></label>
            <label class="order-select-field"><span class="sr-only">合同资料状态</span><select data-contract-filter><option value="all">全部合同资料</option><option value="complete">资料完整</option><option value="incomplete">待补充</option></select></label>
            <label class="order-select-field"><span class="sr-only">人员接入状态</span><select data-access-filter><option value="all">全部接入状态</option><option value="connected">已接入</option><option value="unconnected">未接入</option></select></label>
            <button class="order-secondary-button" type="button" data-reset-factory-filter>重置</button>
            <button class="order-primary-button" type="submit">搜索</button>
          </div>
        </form>
      </section>

      <section class="section-card factory-list-card" aria-labelledby="factory-list-title">
        <header class="order-list-card-header factory-list-header">
          <div class="order-list-heading"><h1 id="factory-list-title">工厂列表</h1></div>
          <button class="order-primary-button" type="button" data-add-factory>新增工厂</button>
        </header>
        <div class="table-scroll">
          <table class="factory-list-table data-grid-table">
            <thead><tr><th scope="col">序号</th>${renderSortableHeader("编号", "supplierNumber")}${renderSortableHeader("工厂名称", "factoryName")}${renderSortableHeader("单位全称", "legalName")}${renderSortableHeader("联系人", "contactName")}${renderSortableHeader("联系电话", "contactPhone")}${renderSortableHeader("合同资料", "contractStatus")}${renderSortableHeader("已接入人员", "connectedUsers")}<th scope="col">操作</th></tr></thead>
            <tbody data-factory-body></tbody>
          </table>
        </div>
        <div class="order-list-footer"><span>每页展示 10 条；上线前将从现有供应商资料初始化 ${factoryListData.sourceTotal} 家工厂。</span><nav class="order-pagination" aria-label="工厂资料分页" data-factory-pagination></nav></div>
      </section>
      <div data-factory-modal-root></div>
    </article>
  `;
}

export function bindFactoryListPage() {
  const page = document.querySelector("[data-factory-list-page]");
  if (!page) return;

  const form = page.querySelector("[data-factory-filter-form]");
  const keywordInput = page.querySelector("[data-factory-keyword]");
  const contractFilter = page.querySelector("[data-contract-filter]");
  const accessFilter = page.querySelector("[data-access-filter]");
  const body = page.querySelector("[data-factory-body]");
  const pagination = page.querySelector("[data-factory-pagination]");
  const modalRoot = page.querySelector("[data-factory-modal-root]");
  const pageSize = 10;
  let currentPage = 1;
  let currentFactories = [...factoryRecords];
  let activeModal = null;
  let sortState = { key: null, direction: "asc" };

  const applyFilters = () => {
    const keyword = normalize(keywordInput?.value);
    const contract = contractFilter?.value ?? "all";
    const access = accessFilter?.value ?? "all";
    const filteredFactories = factoryRecords.filter((factory) => {
      const contactText = (factory.contacts ?? []).flatMap((item) => [item.name, item.phone]);
      const keywordMatch = !keyword || [factory.factoryName, factory.legalName, ...contactText].some((value) => normalize(value).includes(keyword));
      const isComplete = missingContractFields(factory).length === 0;
      const contractMatch = contract === "all" || (contract === "complete" ? isComplete : !isComplete);
      const accessMatch = access === "all" || (access === "connected" ? factory.connectedUsers > 0 : factory.connectedUsers === 0);
      return keywordMatch && contractMatch && accessMatch;
    });
    currentFactories = sortRows(filteredFactories, sortState, factorySortValue);
  };

  const renderPage = () => {
    const totalPages = Math.max(1, Math.ceil(currentFactories.length / pageSize));
    currentPage = Math.min(Math.max(currentPage, 1), totalPages);
    const start = (currentPage - 1) * pageSize;
    body.innerHTML = renderRows(currentFactories.slice(start, start + pageSize), start);
    pagination.innerHTML = renderPagination(currentPage, totalPages, currentFactories.length);
    if (activeModal) {
      const factory = activeModal.mode === "add" ? {} : factoryRecords.find((item) => item.id === activeModal.id);
      modalRoot.innerHTML = activeModal.mode === "detail" ? renderFactoryDetail(factory) : renderEditor(factory, activeModal.mode);
      if (activeModal.mode !== "detail") {
        const focusTarget = activeModal.mode === "edit" ? "[data-contact-name]" : '[name="supplierNumber"]';
        window.requestAnimationFrame(() => modalRoot.querySelector(focusTarget)?.focus());
      }
    } else {
      modalRoot.innerHTML = "";
    }
  };

  const closeModal = () => {
    activeModal = null;
    renderPage();
  };

  form?.addEventListener("submit", (event) => {
    event.preventDefault();
    activeModal = null;
    applyFilters();
    currentPage = 1;
    renderPage();
  });

  page.addEventListener("click", (event) => {
    const nextSortState = getNextSortState(event, sortState);
    if (nextSortState) {
      sortState = nextSortState;
      updateSortHeaders(page, sortState);
      applyFilters();
      currentPage = 1;
      renderPage();
      return;
    }

    const addButton = event.target.closest("[data-add-factory]");
    if (addButton) {
      activeModal = { mode: "add", id: null };
      currentPage = 1;
      renderPage();
      return;
    }

    const editId = event.target.closest("[data-edit-factory]")?.dataset.editFactory;
    if (editId) {
      activeModal = { mode: "edit", id: editId };
      renderPage();
      return;
    }

    const detailId = event.target.closest("[data-view-factory]")?.dataset.viewFactory;
    if (detailId) {
      activeModal = { mode: "detail", id: detailId };
      renderPage();
      return;
    }

    if (event.target.closest("[data-cancel-factory]")) {
      closeModal();
      return;
    }

    if (event.target.matches("[data-factory-modal-backdrop]")) {
      closeModal();
      return;
    }

    const userFactoryId = event.target.closest("[data-view-factory-users]")?.dataset.viewFactoryUsers;
    if (userFactoryId) {
      window.location.hash = `/people?factory=${encodeURIComponent(userFactoryId)}`;
      return;
    }

    const pageNumber = event.target.closest("[data-factory-page]")?.dataset.factoryPage;
    if (pageNumber) {
      activeModal = null;
      currentPage = Number(pageNumber);
      renderPage();
      return;
    }

    const action = event.target.closest("[data-factory-page-action]")?.dataset.factoryPageAction;
    if (action) {
      activeModal = null;
      currentPage += action === "next" ? 1 : -1;
      renderPage();
      return;
    }

    if (event.target.closest("[data-reset-factory-filter]")) {
      form?.reset();
      activeModal = null;
      sortState = { key: null, direction: "asc" };
      updateSortHeaders(page, sortState);
      applyFilters();
      currentPage = 1;
      renderPage();
    }
  });

  page.addEventListener("submit", (event) => {
    const editor = event.target.closest("[data-factory-editor]");
    if (!editor) return;
    event.preventDefault();

    const values = Object.fromEntries(new FormData(editor).entries());
    const supplierNumber = String(values.supplierNumber ?? "").trim().toUpperCase();
    const factoryName = String(values.factoryName ?? "").trim();
    const rawCode = String(values.factoryCode ?? "").trim();
    const prefix = rawCode.split(/[（(-]/, 1)[0]?.trim() ?? "";
    if (rawCode && !/^[A-Za-z]{1,32}$/.test(prefix)) {
      showToast("无法保存", "工厂代码仅支持 1–32 位英文字母");
      return;
    }
    const factoryCode = prefix.toUpperCase();
    const editingId = editor.dataset.factoryId;
    if (!supplierNumber || !factoryName) {
      showToast("无法保存", "编号和工厂名称必须填写。");
      return;
    }
    const duplicateNumber = factoryRecords.some((item) => item.id !== editingId && normalize(item.supplierNumber) === normalize(supplierNumber));
    const duplicateName = factoryRecords.some((item) => item.id !== editingId && normalize(item.factoryName) === normalize(factoryName));
    const duplicateCode = factoryCode && factoryRecords.some((item) => item.id !== editingId && normalize(item.factoryCode) === normalize(factoryCode));
    if (duplicateNumber || duplicateName || duplicateCode) {
      const message = duplicateNumber
        ? "编号已存在，请使用唯一编号。"
        : duplicateName
          ? "工厂名称已存在，请使用唯一名称。"
          : "工厂代码已存在";
      showToast("无法保存", message);
      return;
    }

    const contactNames = [...editor.querySelectorAll("[data-contact-name]")];
    const contactPhones = [...editor.querySelectorAll("[data-contact-phone]")];
    const contacts = contactNames.map((input, index) => ({ name: input.value.trim(), phone: contactPhones[index]?.value.trim() ?? "" })).filter((contact) => contact.name || contact.phone);
    const existingRecord = factoryRecords.find((item) => item.id === editingId);
    const record = {
      id: editingId || `factory-${Date.now()}`,
      supplierNumber,
      factoryName,
      factoryCode,
      legalName: String(values.legalName ?? "").trim(),
      address: String(values.address ?? "").trim(),
      legalRepresentative: String(values.legalRepresentative ?? "").trim(),
      authorizedAgent: existingRecord?.authorizedAgent ?? "",
      contacts,
      bank: existingRecord?.bank ?? "",
      bankAccount: existingRecord?.bankAccount ?? "",
      sourceAliases: existingRecord?.sourceAliases ?? [factoryName],
      connectedUsers: editingId ? factoryRecords.find((item) => item.id === editingId)?.connectedUsers ?? 0 : 0,
    };

    if (editingId) factoryRecords = factoryRecords.map((item) => item.id === editingId ? record : item);
    else factoryRecords = [record, ...factoryRecords];
    activeModal = null;
    applyFilters();
    currentPage = 1;
    renderPage();
    showToast("保存成功", `${factoryName}的工厂资料已更新。`);
  });

  page.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && activeModal) closeModal();
  });

  renderPage();
}
