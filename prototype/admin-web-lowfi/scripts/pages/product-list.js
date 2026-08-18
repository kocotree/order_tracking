import { productListData } from "../mock-data.js";
import { escapeHTML } from "../components/app-shell.js";
import { getNextSortState, renderSortableHeader, sortRows, updateSortHeaders } from "../components/table-sort.js";

const searchIcon = `<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><circle cx="11" cy="11" r="6.5" stroke="currentColor" stroke-width="1.7"/><path d="m16 16 4 4" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/></svg>`;
const productIcon = `<svg viewBox="0 0 28 34" fill="none" aria-hidden="true"><path d="m9 5 5-2 5 2 5 6-4 3v15H8V14l-4-3 5-6Z" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"/><path d="M11 5c.6 2 1.6 3 3 3s2.4-1 3-3" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/></svg>`;

function normalize(value) {
  return String(value).trim().toLocaleLowerCase("zh-CN");
}

function renderRows(products, rowStart = 0) {
  if (products.length === 0) {
    return `<tr><td colspan="6"><div class="empty-state"><div><span class="empty-state-mark">0</span><strong>没有符合条件的产品</strong><p>可以更换货号、产品编码、产品名称或颜色/规格后重新搜索。</p></div></div></td></tr>`;
  }

  return products.map((product, index) => `
    <tr>
      <td class="product-sequence">${rowStart + index + 1}</td>
      <td class="product-item-no">${escapeHTML(product.itemNo)}</td>
      <td><span class="product-list-thumb" aria-label="${product.hasImage ? "产品图片" : "产品图片未上传"}">${productIcon}</span></td>
      <td class="product-code-cell">${escapeHTML(product.productCode)}</td>
      <td><strong class="product-name-cell">${escapeHTML(product.productName)}</strong></td>
      <td>${escapeHTML(product.colorSpec)}</td>
    </tr>
  `).join("");
}

function renderPagination(currentPage, totalPages, totalItems) {
  if (totalItems === 0) return `<span class="order-page-total">共 0 条</span>`;
  const pages = Array.from({ length: totalPages }, (_, index) => {
    const page = index + 1;
    return `<button class="order-page-button${page === currentPage ? " is-current" : ""}" type="button" aria-label="第 ${page} 页" aria-current="${page === currentPage ? "page" : "false"}" data-product-page="${page}">${page}</button>`;
  }).join("");
  return `<span class="order-page-total">共 ${totalItems} 条</span><button class="order-page-button order-page-arrow" type="button" aria-label="上一页" data-product-page-action="prev" ${currentPage === 1 ? "disabled" : ""}>‹</button>${pages}<button class="order-page-button order-page-arrow" type="button" aria-label="下一页" data-product-page-action="next" ${currentPage === totalPages ? "disabled" : ""}>›</button>`;
}

export function renderProductListPage() {
  return `
    <article class="product-list-page" data-product-list-page>
      <section class="order-list-filter-card product-filter-card" aria-label="产品搜索">
        <form class="product-search-form" data-product-search-form>
          <label class="order-list-search-field product-search-field">
            <span class="sr-only">搜索产品资料</span>${searchIcon}
            <input type="search" placeholder="输入货号、产品编码、产品名称或颜色/规格" autocomplete="off" data-product-keyword />
          </label>
          <button class="order-primary-button" type="submit">搜索</button>
        </form>
      </section>

      <section class="section-card product-list-card" aria-labelledby="product-list-title">
        <header class="order-list-card-header">
          <div class="order-list-heading"><h1 id="product-list-title">产品列表</h1></div>
        </header>
        <div class="table-scroll">
          <table class="product-list-table data-grid-table">
            <thead><tr><th scope="col">序号</th>${renderSortableHeader("货号", "itemNo")}<th scope="col">图片</th>${renderSortableHeader("产品编码", "productCode")}${renderSortableHeader("产品名称", "productName")}${renderSortableHeader("颜色/规格", "colorSpec")}</tr></thead>
            <tbody data-product-body></tbody>
          </table>
        </div>
        <div class="order-list-footer"><span>每页展示 10 条产品资料。</span><nav class="order-pagination" aria-label="产品资料分页" data-product-pagination></nav></div>
      </section>
    </article>
  `;
}

export function bindProductListPage() {
  const page = document.querySelector("[data-product-list-page]");
  const form = page?.querySelector("[data-product-search-form]");
  const input = page?.querySelector("[data-product-keyword]");
  const body = page?.querySelector("[data-product-body]");
  const pagination = page?.querySelector("[data-product-pagination]");
  const pageSize = 10;
  let currentPage = 1;
  let filteredProducts = [...productListData.products];
  let currentProducts = [...productListData.products];
  let sortState = { key: null, direction: "asc" };

  const applySort = () => {
    currentProducts = sortRows(filteredProducts, sortState, (product, key) => product[key]);
  };

  const renderPage = () => {
    const totalPages = Math.max(1, Math.ceil(currentProducts.length / pageSize));
    currentPage = Math.min(Math.max(currentPage, 1), totalPages);
    const start = (currentPage - 1) * pageSize;
    if (body) body.innerHTML = renderRows(currentProducts.slice(start, start + pageSize), start);
    if (pagination) pagination.innerHTML = renderPagination(currentPage, totalPages, currentProducts.length);
  };

  form?.addEventListener("submit", (event) => {
    event.preventDefault();
    const keyword = normalize(input?.value ?? "");
    filteredProducts = productListData.products.filter((product) => (
      !keyword || [product.itemNo, product.productCode, product.productName, product.colorSpec].some((value) => normalize(value).includes(keyword))
    ));
    applySort();
    currentPage = 1;
    renderPage();
  });

  page?.addEventListener("click", (event) => {
    const nextSortState = getNextSortState(event, sortState);
    if (nextSortState) {
      sortState = nextSortState;
      updateSortHeaders(page, sortState);
      applySort();
      currentPage = 1;
      renderPage();
      return;
    }

    const pageNumber = event.target.closest("[data-product-page]")?.dataset.productPage;
    if (pageNumber) {
      currentPage = Number(pageNumber);
      renderPage();
      return;
    }
    const action = event.target.closest("[data-product-page-action]")?.dataset.productPageAction;
    if (action) {
      currentPage += action === "next" ? 1 : -1;
      renderPage();
    }
  });

  renderPage();
}
