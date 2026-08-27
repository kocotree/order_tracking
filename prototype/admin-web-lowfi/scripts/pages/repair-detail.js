import { repairListData } from "../mock-data.js";
import { escapeHTML, showToast } from "../components/app-shell.js";
import { getNextSortState, renderSortableHeader, sortRows, updateSortHeaders } from "../components/table-sort.js";

const backIcon = `<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="m15 18-6-6 6-6" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>`;
const fileIcon = `<svg viewBox="0 0 40 44" fill="none" aria-hidden="true"><path d="M8 3h16l8 8v30H8V3Z" stroke="currentColor" stroke-width="1.8"/><path d="M24 3v9h8M13 21h14M13 27h14M13 33h9" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>`;

function formatNumber(value) {
  return new Intl.NumberFormat("zh-CN").format(Number(value) || 0);
}

function getRepair(repairNo) {
  return repairListData.repairs.find((repair) => repair.repairNo === repairNo) ?? repairListData.repairs[0];
}

function renderQualityLines(lines) {
  return lines.map((line, index) => {
    const isFirstInBox = index === 0 || lines[index - 1].boxNo !== line.boxNo;
    let boxRowspan = 1;
    if (isFirstInBox) {
      while (lines[index + boxRowspan]?.boxNo === line.boxNo) boxRowspan += 1;
    }
    const reason = line.reason || "";
    const isFirstReason = index === 0 || (lines[index - 1].reason || "") !== reason;
    let reasonRowspan = 1;
    if (isFirstReason) {
      while (lines[index + reasonRowspan] && (lines[index + reasonRowspan].reason || "") === reason) reasonRowspan += 1;
    }
    return `
    <tr>
      <td class="order-sequence-cell">${index + 1}</td>
      <td class="detail-code">${escapeHTML(line.code)}</td>
      <td>${escapeHTML(line.name)}</td>
      <td>${escapeHTML(line.colorSpec)}</td>
      <td class="repair-number-cell">${escapeHTML(formatNumber(line.quantity))}</td>
      ${isFirstInBox ? `<td class="repair-box-cell" rowspan="${boxRowspan}">${escapeHTML(line.boxNo)}</td>` : ""}
      ${isFirstReason ? `<td class="repair-reason-cell" rowspan="${reasonRowspan}" title="${escapeHTML(line.reason || "—")}">${escapeHTML(line.reason || "—")}</td>` : ""}
    </tr>
  `;
  }).join("");
}

function getWarehouseReturnQuantity(repair, line) {
  return repair.lines
    .filter((qualityLine) => qualityLine.code === line.code && qualityLine.name === line.name && qualityLine.colorSpec === line.colorSpec)
    .reduce((sum, qualityLine) => sum + Number(qualityLine.quantity || 0), 0);
}

function flattenReturnLines(repair) {
  const { returns } = repair;
  return returns.flatMap((record) => {
    const lines = record.lines?.length ? record.lines : [{
      code: "—",
      name: "—",
      colorSpec: "—",
      repairedQuantity: record.repairedQuantity,
      scrappedQuantity: record.scrappedQuantity,
    }];
    return lines.map((line) => ({
      ...line,
      shippedDate: record.shippedAt?.slice(0, 10) || "—",
      returnedQuantity: Number(line.repairedQuantity) + Number(line.scrappedQuantity),
      warehouseReturnQuantity: getWarehouseReturnQuantity(repair, line),
    }));
  });
}

function renderReturnRows(rows) {
  if (!rows.length) {
    return `<tr><td colspan="8"><div class="repair-inline-empty">工厂尚未提交返修发回记录</div></td></tr>`;
  }
  return rows.map((line) => `
      <tr>
        <td>${escapeHTML(line.shippedDate)}</td>
        <td class="detail-code">${escapeHTML(line.code)}</td>
        <td>${escapeHTML(line.name)}</td>
        <td>${escapeHTML(line.colorSpec)}</td>
        <td class="repair-number-cell">${escapeHTML(formatNumber(line.repairedQuantity))}</td>
        <td class="repair-number-cell">${escapeHTML(formatNumber(line.scrappedQuantity))}</td>
        <td class="repair-number-cell">${escapeHTML(formatNumber(line.returnedQuantity))}</td>
        <td class="repair-number-cell">${escapeHTML(formatNumber(line.warehouseReturnQuantity))}</td>
      </tr>
  `).join("");
}

export function renderRepairDetailPage(repairNo) {
  const repair = getRepair(repairNo);
  const returnedTotal = Number(repair.repairedQuantity) + Number(repair.scrappedQuantity);
  return `
    <article class="order-detail-page repair-detail-page" data-repair-detail-page data-repair-no="${escapeHTML(repair.repairNo)}">
      <section class="section-card detail-overview-card">
        <header class="detail-page-header">
          <button class="detail-back-button" type="button" data-repair-detail-back>${backIcon}<span>返回</span></button>
          <div class="detail-title-row repair-detail-title"><strong>${escapeHTML(repair.factory)}</strong></div>
        </header>
        <div class="detail-overview-content">
          <dl class="repair-summary-matrix">
            <div><dt>返修数量</dt><dd>${escapeHTML(formatNumber(repair.repairedQuantity))}</dd></div>
            <div><dt>报废数量</dt><dd>${escapeHTML(formatNumber(repair.scrappedQuantity))}</dd></div>
            <div><dt>仓库退回总数量</dt><dd>${escapeHTML(formatNumber(repair.warehouseReturnQuantity))}</dd></div>
            <div><dt>返回总数量</dt><dd>${escapeHTML(formatNumber(returnedTotal))}</dd></div>
          </dl>
        </div>
      </section>

      <section class="section-card detail-section-card">
        <header class="detail-section-header"><h2>质检单资料</h2></header>
        <div class="repair-source-file">
          <div class="repair-source-file-icon">${fileIcon}</div>
          <div><strong>${escapeHTML(repair.sourceFile)}</strong><span>${escapeHTML(repair.summary.boxCount)} 个箱号 · ${escapeHTML(repair.summary.lineCount)} 条明细 · 仓库退回 ${escapeHTML(formatNumber(repair.warehouseReturnQuantity))} 件</span></div>
          <button class="detail-outline-button" type="button" data-repair-file-download>查看或下载</button>
        </div>
        <div class="detail-table-scroll">
          <table class="detail-data-table repair-quality-table data-grid-table" data-sort-table="repair-quality">
            <thead><tr><th scope="col">序号</th>${renderSortableHeader("产品编码", "code")}${renderSortableHeader("产品名称", "name")}${renderSortableHeader("颜色/规格", "colorSpec")}${renderSortableHeader("仓库退回数量", "quantity")}${renderSortableHeader("箱号", "boxNo")}${renderSortableHeader("次品原因", "reason")}</tr></thead>
            <tbody data-repair-quality-body>${renderQualityLines(repair.lines)}</tbody>
          </table>
        </div>
      </section>

      <section class="section-card detail-section-card">
        <header class="detail-section-header"><h2>工厂发回记录</h2></header>
        <div class="detail-table-scroll">
          <table class="detail-data-table repair-return-table data-grid-table" data-sort-table="repair-returns">
            <thead><tr>${renderSortableHeader("发货日期", "shippedDate")}${renderSortableHeader("产品编码", "code")}${renderSortableHeader("产品名称", "name")}${renderSortableHeader("颜色/规格", "colorSpec")}${renderSortableHeader("返修数量", "repairedQuantity")}${renderSortableHeader("报废数量", "scrappedQuantity")}${renderSortableHeader("返回数量", "returnedQuantity")}${renderSortableHeader("仓库退回数量", "warehouseReturnQuantity")}</tr></thead>
            <tbody data-repair-return-body>${renderReturnRows(flattenReturnLines(repair))}</tbody>
          </table>
        </div>
      </section>
    </article>
  `;
}

export function bindRepairDetailPage(repairNo) {
  const page = document.querySelector("[data-repair-detail-page]");
  const repair = getRepair(repairNo);
  const sortStates = {
    "repair-quality": { key: null, direction: "asc" },
    "repair-returns": { key: null, direction: "asc" },
  };
  page?.querySelector("[data-repair-detail-back]")?.addEventListener("click", () => { window.location.hash = "/repairs"; });
  page?.querySelector("[data-repair-file-download]")?.addEventListener("click", () => showToast("质检单附件", `${repair.sourceFile} 将在正式开发时提供在线查看或下载。`));
  page?.addEventListener("click", (event) => {
    const sortTable = event.target.closest("[data-sort-key]")?.closest("[data-sort-table]");
    const sortScope = sortTable?.dataset.sortTable;
    if (sortScope && sortStates[sortScope]) {
      const nextSortState = getNextSortState(event, sortStates[sortScope]);
      sortStates[sortScope] = nextSortState;
      updateSortHeaders(sortTable, nextSortState);
      if (sortScope === "repair-quality") {
        const lines = sortRows(repair.lines, nextSortState, (line, key) => line[key]);
        page.querySelector("[data-repair-quality-body]").innerHTML = renderQualityLines(lines);
      } else {
        const rows = sortRows(flattenReturnLines(repair), nextSortState, (line, key) => line[key]);
        page.querySelector("[data-repair-return-body]").innerHTML = renderReturnRows(rows);
      }
      return;
    }

  });
}
