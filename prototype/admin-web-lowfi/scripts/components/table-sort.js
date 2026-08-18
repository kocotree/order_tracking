const collator = new Intl.Collator("zh-CN", {
  numeric: true,
  sensitivity: "base",
});

function isEmpty(value) {
  return value === null || value === undefined || value === "";
}

function compareValues(left, right) {
  if (isEmpty(left) && isEmpty(right)) return 0;
  if (isEmpty(left)) return 1;
  if (isEmpty(right)) return -1;
  if (typeof left === "number" && typeof right === "number") return left - right;
  return collator.compare(String(left), String(right));
}

export function renderSortableHeader(label, key, className = "") {
  return `
    <th class="${className}" scope="col" aria-sort="none" data-sort-header="${key}">
      <button class="data-grid-sort-button" type="button" data-sort-key="${key}" aria-label="按${label}升序排序">
        <span>${label}</span>
        <span class="data-grid-sort-arrows" aria-hidden="true">
          <span class="data-grid-sort-arrow is-up"></span>
          <span class="data-grid-sort-arrow is-down"></span>
        </span>
      </button>
    </th>
  `;
}

export function getNextSortState(event, currentState) {
  const button = event.target.closest("[data-sort-key]");
  if (!button) return null;
  const key = button.dataset.sortKey;
  return {
    key,
    direction: currentState.key === key && currentState.direction === "asc" ? "desc" : "asc",
  };
}

export function sortRows(rows, sortState, valueForKey) {
  if (!sortState.key) return [...rows];
  const direction = sortState.direction === "desc" ? -1 : 1;
  return [...rows].sort((left, right) => {
    const leftValue = valueForKey(left, sortState.key);
    const rightValue = valueForKey(right, sortState.key);
    if (isEmpty(leftValue) || isEmpty(rightValue)) return compareValues(leftValue, rightValue);
    return compareValues(leftValue, rightValue) * direction;
  });
}

export function updateSortHeaders(root, sortState) {
  root?.querySelectorAll("[data-sort-header]").forEach((header) => {
    const isActive = header.dataset.sortHeader === sortState.key;
    const direction = isActive ? sortState.direction : "none";
    const button = header.querySelector("[data-sort-key]");
    const label = button?.querySelector("span")?.textContent?.trim() ?? "该列";
    header.setAttribute("aria-sort", direction === "asc" ? "ascending" : direction === "desc" ? "descending" : "none");
    header.classList.toggle("is-sorted", isActive);
    header.classList.toggle("is-sort-desc", isActive && direction === "desc");
    if (button) button.setAttribute("aria-label", `按${label}${direction === "asc" ? "降序" : "升序"}排序`);
  });
}
