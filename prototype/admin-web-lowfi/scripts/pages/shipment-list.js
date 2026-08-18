import { orderListData, shipmentDetailData, shipmentListData } from "../mock-data.js";
import { escapeHTML } from "../components/app-shell.js";
import { getNextSortState, renderSortableHeader, sortRows, updateSortHeaders } from "../components/table-sort.js";

const searchIcon = `<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><circle cx="11" cy="11" r="6.5" stroke="currentColor" stroke-width="1.7"/><path d="m16 16 4 4" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/></svg>`;

function formatNumber(value) {
  return new Intl.NumberFormat("zh-CN").format(Number(value) || 0);
}

function getShipmentProductNames(shipment) {
  const detailNames = shipmentDetailData[shipment.shipmentNo]?.lines?.map((line) => line.name) ?? [];
  const orderNames = shipment.orderNos.map((orderNo) => orderListData.orders.find((order) => order.orderNo === orderNo)?.productName).filter(Boolean);
  const names = [...new Set(detailNames.length > 0 ? detailNames : orderNames)];
  if (names.length === 0) return "—";
  if (names.length === 1) return names[0];
  return `${names.slice(0, 2).join("、")}等`;
}

function renderRows(shipments, rowStart = 0) {
  if (shipments.length === 0) {
    return `<tr><td colspan="8"><div class="empty-state"><div><span class="empty-state-mark">0</span><strong>没有符合当前条件的发货单</strong><p>可以调整搜索词、工厂或发货日期后重新查询。</p></div></div></td></tr>`;
  }

  return shipments.map((shipment, index) => `
    <tr>
      <td class="order-sequence-cell">${rowStart + index + 1}</td>
      <td><button class="row-link" type="button" data-shipment-detail="${escapeHTML(shipment.shipmentNo)}">${escapeHTML(shipment.shipmentNo)}</button></td>
      <td class="shipment-order-cell">${shipment.orderNos.map((orderNo) => `<span>${escapeHTML(orderNo)}</span>`).join("、")}</td>
      <td>${escapeHTML(shipment.factory)}</td>
      <td class="shipment-product-summary" title="${escapeHTML(getShipmentProductNames(shipment))}">${escapeHTML(getShipmentProductNames(shipment))}</td>
      <td class="shipment-number-cell">${escapeHTML(formatNumber(shipment.shippedQuantity))}</td>
      <td>${escapeHTML(shipment.shipDate)}</td>
      <td><button class="order-view-button" type="button" data-shipment-detail="${escapeHTML(shipment.shipmentNo)}">详情</button></td>
    </tr>
  `).join("");
}

function renderPagination(currentPage, totalPages, totalItems) {
  if (totalItems === 0) return `<span class="order-page-total">共 0 条</span>`;
  const pages = Array.from({ length: totalPages }, (_, index) => {
    const page = index + 1;
    return `<button class="order-page-button${page === currentPage ? " is-current" : ""}" type="button" aria-label="第 ${page} 页" aria-current="${page === currentPage ? "page" : "false"}" data-shipment-page="${page}">${page}</button>`;
  }).join("");
  return `<span class="order-page-total">共 ${totalItems} 条</span><button class="order-page-button order-page-arrow" type="button" aria-label="上一页" data-shipment-page-action="prev" ${currentPage === 1 ? "disabled" : ""}>‹</button>${pages}<button class="order-page-button order-page-arrow" type="button" aria-label="下一页" data-shipment-page-action="next" ${currentPage === totalPages ? "disabled" : ""}>›</button>`;
}

export function renderShipmentListPage() {
  const factories = [...new Set(shipmentListData.shipments.map((shipment) => shipment.factory))].sort();
  return `
    <article class="order-list-page shipment-list-page" data-shipment-list-page>
      <section class="order-list-filter-card" aria-label="发货单筛选">
        <form class="order-filter-form" data-shipment-form>
          <div class="order-filter-row shipment-filter-row">
            <label class="order-list-search-field">
              <span class="sr-only">搜索关联订单或发货单号</span>${searchIcon}
              <input type="search" placeholder="输入关联订单或发货单号" autocomplete="off" data-shipment-keyword />
            </label>
            <label class="order-select-field shipment-factory-field">
              <span class="sr-only">选择工厂</span>
              <select data-shipment-factory><option value="">全部工厂</option>${factories.map((factory) => `<option value="${escapeHTML(factory)}">${escapeHTML(factory)}</option>`).join("")}</select>
            </label>
            <label class="order-date-field"><span class="sr-only">发货开始日期</span><input type="date" data-shipment-date-from /></label>
            <span class="order-date-separator">—</span>
            <label class="order-date-field"><span class="sr-only">发货结束日期</span><input type="date" data-shipment-date-to /></label>
            <button class="order-secondary-button" type="button" data-shipment-reset>重置</button>
            <button class="order-primary-button" type="submit">搜索</button>
          </div>
        </form>
      </section>

      <section class="section-card order-list-card" aria-labelledby="shipment-list-title">
        <header class="order-list-card-header"><div class="order-list-heading"><h1 id="shipment-list-title">发货单列表</h1></div></header>
        <div class="table-scroll">
          <table class="orders-table shipment-list-table data-grid-table">
            <thead><tr><th scope="col">序号</th>${renderSortableHeader("发货单号", "shipmentNo")}${renderSortableHeader("关联订单", "orderNos")}${renderSortableHeader("工厂", "factory")}${renderSortableHeader("产品名称", "productNames")}${renderSortableHeader("发货数量", "shippedQuantity")}${renderSortableHeader("发货日期", "shipDate")}<th scope="col">操作</th></tr></thead>
            <tbody data-shipment-body>${renderRows(shipmentListData.shipments)}</tbody>
          </table>
        </div>
        <div class="order-list-footer"><span>每页展示 10 条发货单。</span><nav class="order-pagination" aria-label="发货单分页" data-shipment-pagination></nav></div>
      </section>
    </article>
  `;
}

function normalize(value) {
  return String(value).trim().toLocaleLowerCase("zh-CN");
}

function shipmentSortValue(shipment, key) {
  if (key === "productNames") return getShipmentProductNames(shipment);
  return key === "orderNos" ? shipment.orderNos.join("、") : shipment[key];
}

export function bindShipmentListPage() {
  const page = document.querySelector("[data-shipment-list-page]");
  const form = page?.querySelector("[data-shipment-form]");
  const keywordInput = page?.querySelector("[data-shipment-keyword]");
  const factorySelect = page?.querySelector("[data-shipment-factory]");
  const dateFromInput = page?.querySelector("[data-shipment-date-from]");
  const dateToInput = page?.querySelector("[data-shipment-date-to]");
  const body = page?.querySelector("[data-shipment-body]");
  const pagination = page?.querySelector("[data-shipment-pagination]");
  let currentPage = 1;
  let currentShipments = [];
  let sortState = { key: null, direction: "asc" };
  const pageSize = 10;

  const renderPage = () => {
    const totalPages = Math.max(1, Math.ceil(currentShipments.length / pageSize));
    currentPage = Math.min(Math.max(currentPage, 1), totalPages);
    const start = (currentPage - 1) * pageSize;
    if (body) body.innerHTML = renderRows(currentShipments.slice(start, start + pageSize), start);
    if (pagination) pagination.innerHTML = renderPagination(currentPage, totalPages, currentShipments.length);
  };

  const applyFilters = () => {
    const keyword = normalize(keywordInput?.value ?? "");
    const factory = factorySelect?.value ?? "";
    const dateFrom = dateFromInput?.value ?? "";
    const dateTo = dateToInput?.value ?? "";
    const filteredShipments = shipmentListData.shipments.filter((shipment) => (
      (!keyword || [shipment.shipmentNo, ...shipment.orderNos].some((value) => normalize(value).includes(keyword)))
      && (!factory || shipment.factory === factory)
      && (!dateFrom || shipment.shipDate >= dateFrom)
      && (!dateTo || shipment.shipDate <= dateTo)
    ));
    currentShipments = sortState.key
      ? sortRows(filteredShipments, sortState, shipmentSortValue)
      : filteredShipments.sort((a, b) => b.shipDate.localeCompare(a.shipDate) || b.shipmentNo.localeCompare(a.shipmentNo, "zh-CN"));
    currentPage = 1;
    renderPage();
  };

  form?.addEventListener("submit", (event) => { event.preventDefault(); applyFilters(); });
  factorySelect?.addEventListener("change", applyFilters);
  dateFromInput?.addEventListener("change", applyFilters);
  dateToInput?.addEventListener("change", applyFilters);

  page?.querySelector("[data-shipment-reset]")?.addEventListener("click", () => {
    form?.reset();
    sortState = { key: null, direction: "asc" };
    updateSortHeaders(page, sortState);
    applyFilters();
  });

  page?.addEventListener("click", (event) => {
    const nextSortState = getNextSortState(event, sortState);
    if (nextSortState) {
      sortState = nextSortState;
      updateSortHeaders(page, sortState);
      applyFilters();
      return;
    }

    const shipmentNo = event.target.closest("[data-shipment-detail]")?.dataset.shipmentDetail;
    if (shipmentNo) {
      window.location.hash = `/shipments/${encodeURIComponent(shipmentNo)}`;
      return;
    }
    const pageNumber = event.target.closest("[data-shipment-page]")?.dataset.shipmentPage;
    if (pageNumber) { currentPage = Number(pageNumber); renderPage(); return; }
    const action = event.target.closest("[data-shipment-page-action]")?.dataset.shipmentPageAction;
    if (action) { currentPage += action === "next" ? 1 : -1; renderPage(); }
  });

  applyFilters();
}
