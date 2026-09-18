from datetime import date
from io import BytesIO
from pathlib import Path

from openpyxl import load_workbook

from app.modules.shipments.workbook import (
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
