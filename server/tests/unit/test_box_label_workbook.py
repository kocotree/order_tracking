from io import BytesIO
from pathlib import Path

from openpyxl import load_workbook
from PIL import Image

from app.modules.box_labels.service import BoxLabelService, extract_color, group_id
from app.modules.box_labels.workbook import BoxLabelWorkbookRenderer

TEMPLATE = Path(__file__).resolve().parents[2] / "app/templates/box_label_v1.xlsx"


def test_real_spec_formats_and_ambiguous_color() -> None:
    cases = {
        "冰川蓝110": "冰川蓝",
        "红色120/60": "红色",
        "粉色;XL": "粉色",
        "咖啡;": "咖啡",
        "米色 / 52cm": "米色",
        "23号冰川蓝均码": "23号冰川蓝",
        "蓝色小熊;S": "蓝色小熊",
        "冰川蓝": "冰川蓝",
        "蓝2": None,
        "冰川蓝2026": None,
        "": None,
    }
    assert {value: extract_color(value) for value in cases} == cases
    assert group_id("factory", "product-1", "蓝色") != group_id(
        "factory", "product-2", "蓝色"
    )
    assert BoxLabelService._filename("092#/", {
        "factory": "工/厂", "itemNo": "KQ26168",
        "productName": "暖呼吸", "color": "冰川蓝",
    }) == "092#__工_厂_暖呼吸_冰川蓝.xlsx"


def test_template_and_rendered_labels_keep_two_printable_copies() -> None:
    template = load_workbook(TEMPLATE)
    sheet = template.active
    assert sheet is not None
    assert len(sheet._images) == 0
    assert str(sheet.print_area).endswith("$A$1:$E$18")
    assert sheet["B1"].value == "工厂："
    assert sheet["B11"].value == "工厂："
    assert sheet["B5"].value == sheet["B15"].value == "尺码："
    assert sheet["B8"].value == sheet["B18"].value == "箱号/总箱数："
    assert sheet["E18"].border.right.style is not None

    source = BytesIO()
    Image.new("RGB", (200, 100), "red").save(source, format="PNG")
    values = {
        "factory": "晟衣", "itemNo": "KQ26168",
        "productName": "暖呼吸羽绒马甲", "color": "冰川蓝",
    }
    content = BoxLabelWorkbookRenderer(TEMPLATE).render(values, source.getvalue())
    rendered = load_workbook(BytesIO(content))
    result = rendered.active
    assert result is not None
    assert len(result._images) == 2
    assert [picture.anchor._from.row for picture in result._images] == [1, 11]
    assert str(result.print_area).endswith("$A$1:$E$18")
    for start in (1, 11):
        assert result.cell(start, 2).value == "工厂：晟衣"
        assert result.cell(start + 1, 2).value == "货号：KQ26168"
        assert result.cell(start + 2, 2).value == "品名：暖呼吸羽绒马甲"
        assert result.cell(start + 3, 2).value == "颜色：冰川蓝"
        for offset in (4, 5, 6, 7):
            assert result.cell(start + offset, 2).value == sheet.cell(start + offset, 2).value
