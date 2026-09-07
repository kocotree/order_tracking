export function pageSlots(totalPages, page) {
  const range = (start, count) => Array.from({ length: count }, (_, index) => start + index);
  if (totalPages <= 7) return range(1, totalPages);
  if (page <= 4) return [...range(1, 5), "…", totalPages];
  if (page >= totalPages - 3) return [1, "…", ...range(totalPages - 4, 5)];
  return [1, "…", page - 1, page, page + 1, "…", totalPages];
}

export function renderNumberPagination(page, total, attribute) {
  const pages = Math.max(1, Math.ceil(total / 10));
  const slots = pageSlots(pages, page).map(value => value === "…"
    ? '<span class="order-page-ellipsis" data-page-slot>…</span>'
    : `<button class="order-page-button${value === page ? " is-current" : ""}" data-page-slot type="button" aria-label="第 ${value} 页" ${value === page ? 'aria-current="page"' : ""} ${attribute}="${value}">${value}</button>`).join("");
  return `<span class="order-page-total">共 ${total} 条</span><button class="order-page-button order-page-arrow" type="button" aria-label="上一页" ${attribute}-action="prev" ${page <= 1 ? "disabled" : ""}>‹</button>${slots}<button class="order-page-button order-page-arrow" type="button" aria-label="下一页" ${attribute}-action="next" ${page >= pages ? "disabled" : ""}>›</button>`;
}
