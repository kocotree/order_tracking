from copy import copy
from dataclasses import dataclass
from datetime import date, datetime, time
from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from openpyxl import load_workbook
from openpyxl.workbook.workbook import Workbook
from openpyxl.worksheet.worksheet import Worksheet
from openpyxl.writer.excel import ExcelWriter


class ShipmentWorkbookError(RuntimeError):
    pass


@dataclass(frozen=True)
class ShipmentWorkbookLine:
    order_no: str
    box_no: str
    item_no: str
    product_name: str
    properties_value: str
    packed_quantity: int


@dataclass(frozen=True)
class ShipmentWorkbookSnapshot:
    business_date: date
    total_boxes: int
    lines: list[ShipmentWorkbookLine]


@dataclass(frozen=True)
class DailyShipmentWorkbookLine:
    shipment_no: str
    order_no: str
    box_no: int
    item_no: str
    product_name: str
    properties_value: str
    packed_quantity: int


@dataclass(frozen=True)
class DailyShipmentWorkbookSnapshot:
    factory_name: str
    business_date: date
    shipment_count: int
    total_boxes: int
    lines: list[DailyShipmentWorkbookLine]


class ShipmentWorkbookRenderer:
    DETAIL_START_ROW = 3
    DETAIL_TEMPLATE_END_ROW = 23

    def __init__(self, *, template_path: Path) -> None:
        self._template_path = template_path

    def render(self, snapshot: ShipmentWorkbookSnapshot) -> bytes:
        if not snapshot.lines:
            raise ShipmentWorkbookError("shipment workbook requires detail lines")
        if snapshot.total_boxes <= 0:
            raise ShipmentWorkbookError("shipment workbook requires boxes")
        workbook = load_workbook(self._template_path)
        if workbook.sheetnames != ["发货明细", "汇总", "Sheet3"]:
            raise ShipmentWorkbookError("shipment template sheets are invalid")
        workbook.remove(workbook["Sheet3"])
        detail = workbook["发货明细"]
        summary = workbook["汇总"]
        self._write_detail(detail, snapshot)
        self._write_summary(summary, snapshot)
        return self._save(workbook, snapshot.business_date)

    def render_daily(self, snapshot: DailyShipmentWorkbookSnapshot) -> bytes:
        if not snapshot.lines:
            raise ShipmentWorkbookError("daily shipment workbook requires detail lines")
        workbook = load_workbook(self._template_path)
        if workbook.sheetnames != ["发货明细", "汇总", "Sheet3"]:
            raise ShipmentWorkbookError("shipment template sheets are invalid")
        workbook.remove(workbook["Sheet3"])
        self._write_daily_detail(workbook["发货明细"], snapshot)
        self._write_summary(
            workbook["汇总"],
            ShipmentWorkbookSnapshot(
                business_date=snapshot.business_date,
                total_boxes=snapshot.total_boxes,
                lines=[
                    ShipmentWorkbookLine(
                        order_no=line.order_no,
                        box_no=str(line.box_no),
                        item_no=line.item_no,
                        product_name=line.product_name,
                        properties_value=line.properties_value,
                        packed_quantity=line.packed_quantity,
                    )
                    for line in snapshot.lines
                ],
            ),
        )
        return self._save(workbook, snapshot.business_date)

    @staticmethod
    def _save(workbook: Workbook, business_date: date) -> bytes:
        workbook.properties.modified = datetime.combine(business_date, time.min)
        output = BytesIO()
        ExcelWriter(workbook, ZipFile(output, "w", ZIP_DEFLATED, allowZip64=True)).save()
        normalized = BytesIO()
        with ZipFile(output) as source, ZipFile(normalized, "w") as target:
            for entry in source.infolist():
                content = source.read(entry)
                entry.date_time = (1980, 1, 1, 0, 0, 0)
                target.writestr(entry, content)
        return normalized.getvalue()

    @classmethod
    def _prepare_detail_rows(cls, sheet: Worksheet, line_count: int) -> None:
        template_capacity = cls.DETAIL_TEMPLATE_END_ROW - cls.DETAIL_START_ROW + 1
        extra_rows = max(line_count - template_capacity, 0)
        if extra_rows:
            sheet.insert_rows(cls.DETAIL_TEMPLATE_END_ROW + 1, extra_rows)
            source_row = cls.DETAIL_TEMPLATE_END_ROW
            for row_index in range(source_row + 1, source_row + extra_rows + 1):
                sheet.row_dimensions[row_index].height = sheet.row_dimensions[source_row].height
                for column in range(1, 8):
                    source = sheet.cell(source_row, column)
                    target = sheet.cell(row_index, column)
                    target._style = copy(source._style)  # type: ignore[union-attr]
                    target.number_format = source.number_format
                    target.alignment = copy(source.alignment)  # type: ignore[assignment]
                    target.protection = copy(source.protection)  # type: ignore[assignment]
        detail_end = cls.DETAIL_START_ROW + max(line_count, template_capacity) - 1
        for row in sheet.iter_rows(
            min_row=cls.DETAIL_START_ROW,
            max_row=detail_end,
            min_col=1,
            max_col=7,
        ):
            for cell in row:
                cell.value = None

    @classmethod
    def _write_detail(cls, sheet: Worksheet, snapshot: ShipmentWorkbookSnapshot) -> None:
        value = snapshot.business_date
        sheet["A1"] = (
            f"KK发货清单 {value.year}年{value.month}月{value.day}日 共计{snapshot.total_boxes}箱"
        )
        is_mixed = len({line.box_no for line in snapshot.lines}) < len(snapshot.lines)
        if is_mixed:
            headers = ("订单编号", "箱号", "货号", "品名", "颜色/规格", "装箱数量", "合计")
            rows: list[tuple[str | int, ...]] = [
                (
                    line.order_no,
                    line.box_no,
                    line.item_no,
                    line.product_name,
                    line.properties_value,
                    line.packed_quantity,
                    line.packed_quantity,
                )
                for line in snapshot.lines
            ]
            total_box_column = 2
        else:
            headers = ("订单编号", "货号", "品名", "颜色/规格", "箱数", "装箱数量", "合计")
            grouped: dict[tuple[str, str, str, int], tuple[str, int]] = {}
            for line in snapshot.lines:
                key = (
                    line.order_no,
                    line.item_no,
                    line.properties_value,
                    line.packed_quantity,
                )
                product_name, box_count = grouped.get(key, (line.product_name, 0))
                grouped[key] = (product_name, box_count + 1)
            rows = [
                (
                    order_no,
                    item_no,
                    product_name,
                    properties_value,
                    box_count,
                    quantity,
                    box_count * quantity,
                )
                for (order_no, item_no, properties_value, quantity), (
                    product_name,
                    box_count,
                ) in grouped.items()
            ]
            total_box_column = 5

        cls._prepare_detail_rows(sheet, len(rows) + 1)
        for column, header in enumerate(headers, 1):
            sheet.cell(2, column, header)
        for offset, values in enumerate(rows):
            row = cls.DETAIL_START_ROW + offset
            for column, cell_value in enumerate(values, 1):
                sheet.cell(row, column, cell_value)
        total_row = cls.DETAIL_START_ROW + len(rows)
        sheet.cell(total_row, 1, "汇总")
        sheet.cell(total_row, total_box_column, snapshot.total_boxes)
        sheet.cell(total_row, 7, sum(line.packed_quantity for line in snapshot.lines))

    @classmethod
    def _write_daily_detail(
        cls, sheet: Worksheet, snapshot: DailyShipmentWorkbookSnapshot
    ) -> None:
        total_quantity = sum(line.packed_quantity for line in snapshot.lines)
        sheet["A1"] = (
            f"KK发货汇总 {snapshot.factory_name} {snapshot.business_date:%Y-%m-%d} "
            f"共计{snapshot.shipment_count}单 {snapshot.total_boxes}箱 {total_quantity}件"
        )
        cls._prepare_detail_rows(sheet, len(snapshot.lines) + 1)
        headers = ("发货单号", "订单编号", "箱号", "货号", "品名", "颜色/规格", "装箱数量")
        for column, header in enumerate(headers, 1):
            sheet.cell(2, column, header)
        for offset, line in enumerate(snapshot.lines):
            row = cls.DETAIL_START_ROW + offset
            values: tuple[str | int, ...] = (
                line.shipment_no,
                line.order_no,
                line.box_no,
                line.item_no,
                line.product_name,
                line.properties_value,
                line.packed_quantity,
            )
            for column, value in enumerate(
                values,
                1,
            ):
                sheet.cell(row, column, value)
        total_row = cls.DETAIL_START_ROW + len(snapshot.lines)
        sheet.cell(total_row, 1, "汇总")
        sheet.cell(total_row, 3, snapshot.total_boxes)
        sheet.cell(total_row, 7, total_quantity)

    @staticmethod
    def _write_summary(sheet: Worksheet, snapshot: ShipmentWorkbookSnapshot) -> None:
        if sheet.max_row > 1:
            sheet.delete_rows(2, sheet.max_row - 1)
        for column, header in enumerate(("日期", "货号", "名称", "颜色/规格", "数量"), 1):
            sheet.cell(1, column, header)
        sheet["E1"]._style = copy(sheet["D1"]._style)
        totals: dict[tuple[str, str], tuple[str, int]] = {}
        for line in snapshot.lines:
            key = (line.item_no, line.properties_value)
            product_name, quantity = totals.get(key, (line.product_name, 0))
            totals[key] = (product_name, quantity + line.packed_quantity)
        for row, ((item_no, properties_value), (product_name, quantity)) in enumerate(
            sorted(totals.items()), 2
        ):
            sheet.cell(row, 1, snapshot.business_date)
            sheet.cell(row, 1).number_format = "yyyy-mm-dd"
            sheet.cell(row, 2, item_no)
            sheet.cell(row, 3, product_name)
            sheet.cell(row, 4, properties_value)
            sheet.cell(row, 5, quantity)
