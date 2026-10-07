from datetime import date
from io import BytesIO
from pathlib import Path
from time import sleep

from openpyxl import load_workbook
from openpyxl.cell.cell import MergedCell

from app.modules.shipments.workbook import (
    DailyShipmentWorkbookLine,
    DailyShipmentWorkbookSnapshot,
    ShipmentWorkbookLine,
    ShipmentWorkbookRenderer,
    ShipmentWorkbookSnapshot,
)


def test_single_item_boxes_use_summary_template_and_merge_matching_nonconsecutive_boxes() -> None:
    template = Path(__file__).resolve().parents[3] / "docs/reference/厂家发货模版.xlsx"
    renderer = ShipmentWorkbookRenderer(template_path=template)

    content = renderer.render(
        ShipmentWorkbookSnapshot(
            business_date=date(2026, 8, 25),
            total_boxes=6,
            lines=[
                ShipmentWorkbookLine("ORDER-A", "1", "ITEM-001", "遮阳帽", "米白 / 52cm", 6),
                ShipmentWorkbookLine("ORDER-B", "2", "ITEM-001", "遮阳帽", "米白 / 52cm", 4),
                ShipmentWorkbookLine("ORDER-A", "3", "ITEM-001", "遮阳帽", "米白 / 52cm", 6),
                ShipmentWorkbookLine("ORDER-A", "4", "ITEM-001", "遮阳帽", "米白 / 52cm", 3),
                ShipmentWorkbookLine("ORDER-A", "5", "ITEM-002", "渔夫帽", "卡其 / 52cm", 2),
                ShipmentWorkbookLine("ORDER-A", "6", "ITEM-001", "遮阳帽", "黑色 / 54cm", 6),
            ],
        )
    )

    workbook = load_workbook(BytesIO(content), data_only=False)
    assert workbook.sheetnames == ["发货明细", "汇总"]
    detail = workbook["发货明细"]
    assert detail["A1"].value == "KK发货清单 2026年8月25日 共计6箱"
    assert [detail.cell(2, column).value for column in range(1, 8)] == [
        "订单编号",
        "货号",
        "品名",
        "颜色/规格",
        "箱数",
        "装箱数量",
        "合计",
    ]
    assert [[detail.cell(row, column).value for column in range(1, 8)] for row in range(3, 8)] == [
        ["ORDER-A", "ITEM-001", "遮阳帽", "米白 / 52cm", 2, 6, 12],
        ["ORDER-B", "ITEM-001", "遮阳帽", "米白 / 52cm", 1, 4, 4],
        ["ORDER-A", "ITEM-001", "遮阳帽", "米白 / 52cm", 1, 3, 3],
        ["ORDER-A", "ITEM-002", "渔夫帽", "卡其 / 52cm", 1, 2, 2],
        ["ORDER-A", "ITEM-001", "遮阳帽", "黑色 / 54cm", 1, 6, 6],
    ]
    assert [detail.cell(8, column).value for column in range(1, 8)] == [
        "汇总",
        None,
        None,
        None,
        6,
        None,
        27,
    ]

    summary = workbook["汇总"]
    assert [summary.cell(1, column).value for column in range(1, 6)] == [
        "日期",
        "货号",
        "名称",
        "颜色/规格",
        "数量",
    ]
    assert summary["A2"].value.date() == date(2026, 8, 25)
    assert [[summary.cell(row, column).value for column in range(2, 6)] for row in range(2, 5)] == [
        ["ITEM-001", "遮阳帽", "米白 / 52cm", 19],
        ["ITEM-001", "遮阳帽", "黑色 / 54cm", 6],
        ["ITEM-002", "渔夫帽", "卡其 / 52cm", 2],
    ]
    assert summary.max_row == 4


def test_any_mixed_box_keeps_each_box_line_and_adds_totals() -> None:
    template = Path(__file__).resolve().parents[3] / "docs/reference/厂家发货模版.xlsx"
    content = ShipmentWorkbookRenderer(template_path=template).render(
        ShipmentWorkbookSnapshot(
            business_date=date(2026, 9, 18),
            total_boxes=2,
            lines=[
                ShipmentWorkbookLine("ORDER-A", "1", "ITEM-001", "遮阳帽", "米白 / 52cm", 6),
                ShipmentWorkbookLine("ORDER-A", "1", "ITEM-002", "渔夫帽", "卡其 / 52cm", 2),
                ShipmentWorkbookLine("ORDER-A", "2", "ITEM-001", "遮阳帽", "米白 / 52cm", 4),
            ],
        )
    )

    detail = load_workbook(BytesIO(content), data_only=False)["发货明细"]
    assert [detail.cell(2, column).value for column in range(1, 8)] == [
        "订单编号",
        "箱号",
        "货号",
        "品名",
        "颜色/规格",
        "装箱数量",
        "合计",
    ]
    assert [[detail.cell(row, column).value for column in range(1, 8)] for row in range(3, 6)] == [
        ["ORDER-A", "1", "ITEM-001", "遮阳帽", "米白 / 52cm", 6, 6],
        ["ORDER-A", "1", "ITEM-002", "渔夫帽", "卡其 / 52cm", 2, 2],
        ["ORDER-A", "2", "ITEM-001", "遮阳帽", "米白 / 52cm", 4, 4],
    ]
    assert [detail.cell(6, column).value for column in range(1, 8)] == [
        "汇总",
        2,
        None,
        None,
        None,
        None,
        12,
    ]


def test_repeated_exports_have_identical_bytes() -> None:
    template = Path(__file__).resolve().parents[3] / "docs/reference/厂家发货模版.xlsx"
    renderer = ShipmentWorkbookRenderer(template_path=template)
    shipment = ShipmentWorkbookSnapshot(
        business_date=date(2026, 9, 21),
        total_boxes=1,
        lines=[ShipmentWorkbookLine("ORDER-A", "1", "ITEM-001", "遮阳帽", "米白", 6)],
    )
    daily = DailyShipmentWorkbookSnapshot(
        factory_name="工厂A",
        business_date=date(2026, 9, 21),
        shipment_count=1,
        total_boxes=1,
        lines=[
            DailyShipmentWorkbookLine(
                "SHIP-001",
                "ORDER-A",
                1,
                "ITEM-001",
                "遮阳帽",
                "米白",
                6,
            )
        ],
    )
    first_shipment = renderer.render(shipment)
    first_daily = renderer.render_daily(daily)
    sleep(2.1)
    assert renderer.render(shipment) == first_shipment
    assert renderer.render_daily(daily) == first_daily


def test_daily_summary_layout_merges_dates_names_and_keeps_purchase_orders() -> None:
    template = Path(__file__).resolve().parents[3] / "docs/reference/厂家发货模版.xlsx"
    content = ShipmentWorkbookRenderer(template_path=template).render_daily(
        DailyShipmentWorkbookSnapshot(
            factory_name="工厂A", business_date=date(2026, 10, 6),
            shipment_count=2, total_boxes=4,
            lines=[
                DailyShipmentWorkbookLine("S1", "O1", 1, "I1", "帽子", "白", 6, "001"),
                DailyShipmentWorkbookLine("S2", "O2", 1, "I1", "帽子", "白", 4, "002"),
                DailyShipmentWorkbookLine("S2", "O2", 2, "I1", "帽子", "黑", 3, "002"),
                DailyShipmentWorkbookLine("S2", "O2", 3, "I2", "衣服", "蓝", 2),
            ],
        )
    )
    workbook = load_workbook(BytesIO(content))
    sheet = workbook["汇总"]
    assert sheet["A1"].value == "KK发货汇总 工厂A 2026-10-06 共计15件"
    assert list(sheet.values)[1] == (
        "日期", "名称", "颜色/规格", "数量", "单价", "总金额", "采购单号", "入库单号"
    )
    assert sheet["A3"].value.date() == date(2026, 10, 6)
    assert sheet["A3"].number_format == "m.d"
    assert {str(value) for value in sheet.merged_cells.ranges} == {
        "A1:H1", "A3:A5", "B3:B4"
    }
    assert [list(row)[1:] for row in list(sheet.values)[2:5]] == [
        ["帽子", "白", 10, None, None, "001、002", None],
        [None, "黑", 3, None, None, "002", None],
        ["衣服", "蓝", 2, None, None, None, None],
    ]
    assert list(sheet.values)[5] == ("汇总", None, None, 15, None, None, None, None)
    assert workbook["发货明细"]["A1"].value.endswith("共计2单 4箱 15件")
    for row in sheet.iter_rows():
        for cell in row:
            if not isinstance(cell, MergedCell):
                assert cell.alignment.horizontal == "center"
                assert cell.alignment.vertical == "center"
            if cell.row == 1:
                assert all(getattr(cell.border, side).style is None
                           for side in ("left", "right", "top", "bottom"))
                continue
            for side in ("left", "right", "top", "bottom"):
                border = getattr(cell.border, side)
                internal = isinstance(cell, MergedCell) and (
                    side == "top" or (side == "bottom" and cell.coordinate == "A4")
                )
                assert border.style == (None if internal else "thin")
                if not internal:
                    assert border.color.rgb == "00000000"
