# ruff: noqa: E501

from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import pytest
from openpyxl import load_workbook
from PIL import Image

from app.modules.contracts.workbook import ContractWorkbookRenderer

V2_FIXED_TEXT = [
    "合同条款：",
    "一. 乙方保证具备合法的生产经营资质及开具符合甲方抵扣要求的增值税普通发票的能力",
    "二. 付款方式：加工费按检品合格后实际交货数量,月结30天内付清，乙方须先行开具税率为 [ 1% ] 的增值税普通发票给甲方，",
    "    甲方在收到合规发票并验收合格后，按约定账期支付货款。未收到合规发票的，甲方有权拒绝付款。",
    "三．交货地点：浙江省嘉兴市桐乡市凤鸣街道高新西三路1399号浙江酷趣智能工厂  罗小波 15268701248",
    "四．运输方式及运费承担：乙方负责将成品货物运输至甲方指定仓库，货物在甲方验收合格入库前的毁损、灭失风险由乙方承担。",
    "五. 质量要求、技术标准：乙方严格按照客户要求或确认样组织生产，所有产品必须本厂生产，不准外发。所有产品必须达到样品的要求，无线头整体保持整洁等。",
    "    出货后若出现品质量问题，由乙方承担所有损失。",
    "    当乙方成品质量检验合格率低于90%以下，甲方有权撤回所有订单以及材料，解除合同，并追究乙方承担甲方的产品损失。",
    "    如出现质量问题的，甲方可选择退货或者换货（乙方应在20天内返修好），由此产生的运费以及毁损灭失的风险等由乙方承担。",
    "    本合同产品实际由乙方生产，为了保护甲方的商业机密，故产品吊牌生产厂商标注为甲方。如乙方生产的产品，在销售等过程中出现抽检不合格等产生的案",
    "    件，双方同意将案件等转移到乙方所在地市场监管部门依法处理。",
    "六. 验收标准、方法：按照甲方提供的验收标准验收。",
    "七. 如乙方无故逾期交货的，应按照逾期10天以上不包含10天，每逾期一日，乙方按该批次加工款1%，累计上限不超过本批次加工总价款30%支付违约金，",
    "违约金甲方可直接从加工尾款中扣除。",
    "八. 权益要求：本合同内容为甲方商业秘密，本合同项下产品的设计图纸、模具、样板等知识产权归甲方所有，乙方不得用于生产第三方产品或自行销售",
    "如乙方发生泄漏的，应按照合同约定总价的3倍进行赔偿（如实际损失超过该金额的，按照实际损失进行赔偿）。",
    "所有产品乙方只提供给甲方，不得私自生产和销售，配合保护甲方的品牌及相应的知识产权。",
    "九. 乙方应妥善保管面辅料，正常损耗率不超过物控表用量，超出部分的损耗或人为浪费，乙方应按采购价赔偿。",
    "十. 禁止商业贿赂：双方在合作期间、员工劳动合同履行期间，以及双方合作结束后，各方均不得聘用对方的工作人员，不得有让对方工作人",
    "员来自己单位工作（包括但不限于劳动关系、劳务关系、帮工等）的意思表示，乙方不得以任何手段或方式给予甲方工作人员财物（包括但不",
    "限于佣金或者回扣等），如发生的认定乙方违反《反不正当竞争法》，甲方有权单方解除合同，要求乙方按照合同约定总价的3倍进行赔偿",
    "（如实际损失超过该金额的，按照实际损失进行赔偿）。并依法追究刑事责任。",
    "十一.如产品被平台或者有关部门抽检出现不合格项目导致的罚款，一律由乙方承担(仅乙方加工所产生的品质问题）。",
    "十二. 本合同一式二份，双方各执一份，经双方签字或者盖章后即生效。",
    "补充栏：双方就本合同发生的纠纷由甲方所在地人民法院管辖）________________________________________________________________________",
]


def test_v2_renderer_uses_confirmed_fixed_text_and_keeps_manual_fields_blank() -> None:
    template = Path(__file__).resolve().parents[2] / "app/templates/processing_contract_v2.xlsx"
    renderer = ContractWorkbookRenderer(template_paths={"v2": template})

    content = renderer.render(
        _snapshot(
            [
                {
                    "productId": "product-1",
                    "itemNo": "MZ2026-01",
                    "productName": "儿童遮阳帽",
                    "propertiesValue": "米色 / 52cm",
                    "quantity": 40,
                    "imageObjectKey": None,
                }
            ]
        ),
        template_version="v2",
    )

    workbook = load_workbook(BytesIO(content), data_only=False)
    sheet = workbook["合同"]
    assert workbook.sheetnames == ["合同"]
    assert sheet["A3"].value == "甲方（需方）：浙江酷趣智能科技有限公司"
    assert sheet["A4"].value == "乙方（供方）：合同测试工厂有限公司"
    assert sheet["H8"].value is None
    assert sheet["I8"].value is None
    assert sheet["A22"].value == (
        "备注：加工单价不含税，含车缝、车缝线，整烫、品检、清洁，纸箱，防水PE袋，单趟运输费用，不含挂吊牌及独立包装。"
        "次品品检费由乙方承担0.7元/件。"
    )
    assert [sheet.cell(row, 1).value for row in range(23, 49)] == V2_FIXED_TEXT
    assert "交货期限" not in "".join(
        str(cell.value or "") for row in sheet.iter_rows() for cell in row
    )
    assert sheet["A49"].value.startswith("                 甲      方\n")
    assert sheet["E49"].value == (
        "                      乙     方\n"
        "单位名称（章）：合同测试工厂有限公司\n"
        "单位地址：浙江省杭州市测试路1号\n"
        "法定代表人：测试法人\n"
        "委托代理人：\n"
        "开户银行：\n"
        "账号：\n"
        "电话："
    )
    with ZipFile(BytesIO(content)) as archive:
        names = archive.namelist()
        assert not any("cellimages" in name.lower() for name in names)
        unsafe = ("vbaProject", "externalLink", "oleObject", "embeddings")
        assert not any(any(marker in name for marker in unsafe) for name in names)


def _snapshot(lines: list[dict[str, object]]) -> dict[str, object]:
    return {
        "contractNo": "20260824-KK-HT",
        "signingDate": "2026-08-24",
        "orderNo": "HT-ORDER-BOUNDARY",
        "contractShipDate": "2026-09-10",
        "factory": {
            "legalName": "合同测试工厂有限公司",
            "address": "浙江省杭州市测试路1号",
            "legalRepresentative": "测试法人",
            "phone": "",
        },
        "lines": lines,
    }


@pytest.mark.parametrize("line_count", [1, 12])
def test_renderer_supports_original_detail_area_boundaries(line_count: int) -> None:
    template = Path(__file__).resolve().parents[2] / "app/templates/processing_contract_v1.xlsx"
    renderer = ContractWorkbookRenderer(template_path=template)
    lines = [
        {
            "productId": "product-1",
            "itemNo": "MZ2026-01",
            "productName": "儿童遮阳帽",
            "propertiesValue": f"规格 {index + 1}",
            "quantity": index + 1,
            "imageObjectKey": None,
        }
        for index in range(line_count)
    ]

    content = renderer.render(_snapshot(lines))

    sheet = load_workbook(BytesIO(content), data_only=False)["合同"]
    last_row = 7 + line_count
    assert sheet.cell(last_row, 4).value == f"规格 {line_count}"
    assert sheet["E20"].value == f"=SUM(E8:E{last_row})"
    assert str(sheet.print_area) == "'合同'!$A$1:$I$51"
    with ZipFile(BytesIO(content)) as archive:
        unsafe = ("vbaProject", "externalLink", "oleObject", "embeddings")
        assert not any(any(marker in name for marker in unsafe) for name in archive.namelist())


def test_renderer_keeps_template_layout_and_leaves_prices_and_incomplete_totals_blank() -> None:
    template = Path(__file__).resolve().parents[2] / "app/templates/processing_contract_v1.xlsx"
    renderer = ContractWorkbookRenderer(template_path=template)

    content = renderer.render(
        {
            "contractNo": "20260824-KK-HT",
            "signingDate": "2026-08-24",
            "orderNo": "HT-ORDER-001",
            "contractShipDate": "2026-09-10",
            "factory": {
                "legalName": "合同测试工厂有限公司",
                "address": "浙江省杭州市测试路1号",
                "legalRepresentative": "测试法人",
                "phone": "13800000000",
            },
            "lines": [
                {
                    "productId": "product-1",
                    "itemNo": "MZ2026-01",
                    "productName": "儿童遮阳帽",
                    "propertiesValue": "米色 / 52cm",
                    "quantity": 40,
                    "imageObjectKey": None,
                },
                {
                    "productId": "product-1",
                    "itemNo": "MZ2026-01",
                    "productName": "儿童遮阳帽",
                    "propertiesValue": "米色 / 54cm",
                    "quantity": 60,
                    "imageObjectKey": None,
                },
            ],
        }
    )

    workbook = load_workbook(BytesIO(content), data_only=False)
    sheet = workbook["合同"]
    assert workbook.sheetnames == ["合同"]
    assert sheet["G3"].value == "合同编号：20260824-KK-HT"
    assert sheet["G4"].value == "签订时间：2026年8月24日"
    assert sheet["A4"].value == "供方：合同测试工厂有限公司"
    assert sheet["A8"].value == "MZ2026-01"
    assert sheet["B8"].value == "儿童遮阳帽"
    assert sheet["D8"].value == "米色 / 52cm"
    assert sheet["D9"].value == "米色 / 54cm"
    assert sheet["E8"].value == 40
    assert sheet["E9"].value == 60
    assert sheet["F8"].value is None
    assert sheet["F9"].value is None
    assert sheet["G8"].value == '=IF(OR(E8="",F8=""),"",E8*F8)'
    assert sheet["G9"].value == '=IF(OR(E9="",F9=""),"",E9*F9)'
    assert sheet["G10"].value is None
    assert sheet["E20"].value == "=SUM(E8:E9)"
    assert sheet["G20"].value == '=IF(COUNT(F8:F9)=ROWS(F8:F9),SUM(G8:G9),"")'
    assert sheet["B21"].value == '=IF(G20="","",G20)'
    assert sheet["D21"].value == '=IF(G20="","",G20)'
    assert "A8:A9" in {str(item) for item in sheet.merged_cells.ranges}
    assert "B8:B9" in {str(item) for item in sheet.merged_cells.ranges}
    assert "C8:C9" in {str(item) for item in sheet.merged_cells.ranges}
    assert "H8:H19" in {str(item) for item in sheet.merged_cells.ranges}
    assert sheet["H8"].value is None
    assert sheet["A24"].value == "一.交货期限：    年    月    日前全部出货"
    assert "合同测试工厂有限公司" in sheet["E45"].value
    assert "委托代理人：\n开户银行：\n账号：\n电话：13800000000" in sheet["E45"].value
    assert all(
        cell.fill.fill_type is None
        for row in sheet.iter_rows(min_row=1, max_row=51, min_col=1, max_col=9)
        for cell in row
    )
    assert "南昌昱斌" not in "".join(
        str(cell.value or "") for row in sheet.iter_rows() for cell in row
    )


@pytest.mark.parametrize(
    ("line_count", "total_row", "signature_row", "print_end"),
    [(12, 20, 49, 55), (13, 21, 50, 56)],
)
def test_v2_renderer_keeps_fixed_sections_after_detail_rows(
    line_count: int, total_row: int, signature_row: int, print_end: int
) -> None:
    template = Path(__file__).resolve().parents[2] / "app/templates/processing_contract_v2.xlsx"
    renderer = ContractWorkbookRenderer(template_paths={"v2": template})
    lines = [
        {
            "productId": "product-1",
            "itemNo": "MZ2026-01",
            "productName": "儿童遮阳帽",
            "propertiesValue": f"规格 {index + 1}",
            "quantity": index + 1,
            "imageObjectKey": None,
        }
        for index in range(line_count)
    ]

    content = renderer.render(
        {
            "contractNo": "20260824-KK-HT-1",
            "signingDate": "2026-08-24",
            "orderNo": "HT-ORDER-002",
            "contractShipDate": "2026-09-10",
            "factory": {
                "legalName": "合同测试工厂有限公司",
                "address": "浙江省杭州市测试路1号",
                "legalRepresentative": "测试法人",
                "phone": "",
            },
            "lines": lines,
        },
        template_version="v2",
    )

    workbook = load_workbook(BytesIO(content), data_only=False)
    sheet = workbook["合同"]
    last_row = 7 + line_count
    assert sheet.cell(last_row, 4).value == f"规格 {line_count}"
    assert sheet.cell(last_row, 7).value == (
        f'=IF(OR(E{last_row}="",F{last_row}=""),"",E{last_row}*F{last_row})'
    )
    assert sheet.cell(total_row, 5).value == f"=SUM(E8:E{last_row})"
    assert sheet.cell(total_row, 7).value == (
        f'=IF(COUNT(F8:F{last_row})=ROWS(F8:F{last_row}),SUM(G8:G{last_row}),"")'
    )
    assert f"A8:A{last_row}" in {str(item) for item in sheet.merged_cells.ranges}
    assert "合同测试工厂有限公司" in sheet.cell(signature_row, 5).value
    assert sheet.cell(23 + max(line_count - 12, 0), 1).value == "合同条款："
    assert str(sheet.print_area) == f"'合同'!$A$1:$I${print_end}"


def test_renderer_embeds_available_product_image_once_for_product_group() -> None:
    template = Path(__file__).resolve().parents[2] / "app/templates/processing_contract_v2.xlsx"
    image_bytes = BytesIO()
    Image.new("RGB", (200, 100), color=(20, 100, 70)).save(image_bytes, format="PNG")
    renderer = ContractWorkbookRenderer(
        template_paths={"v2": template},
        image_loader=lambda object_key: image_bytes.getvalue()
        if object_key == "products/hat.png"
        else None,
    )

    content = renderer.render(
        {
            "contractNo": "20260824-KK-HT-2",
            "signingDate": "2026-08-24",
            "orderNo": "HT-ORDER-003",
            "contractShipDate": "2026-09-10",
            "factory": {
                "legalName": "合同测试工厂有限公司",
                "address": "浙江省杭州市测试路1号",
                "legalRepresentative": "测试法人",
                "phone": "",
            },
            "lines": [
                {
                    "productId": "product-1",
                    "itemNo": "MZ2026-01",
                    "productName": "儿童遮阳帽",
                    "propertiesValue": "米色 / 52cm",
                    "quantity": 40,
                    "imageObjectKey": "products/hat.png",
                },
                {
                    "productId": "product-1",
                    "itemNo": "MZ2026-01",
                    "productName": "儿童遮阳帽",
                    "propertiesValue": "米色 / 54cm",
                    "quantity": 60,
                    "imageObjectKey": "products/hat.png",
                },
            ],
        },
        template_version="v2",
    )

    workbook = load_workbook(BytesIO(content))
    sheet = workbook["合同"]
    assert len(sheet._images) == 1
    image = sheet._images[0]
    assert image.anchor._from.col == 2
    assert image.anchor._from.row == 7


def test_renderer_preserves_table_styles_for_each_product_group() -> None:
    template = Path(__file__).resolve().parents[2] / "app/templates/processing_contract_v1.xlsx"
    renderer = ContractWorkbookRenderer(template_path=template)
    lines = [
        {
            "productId": f"product-{index}",
            "itemNo": f"ITEM-{index}",
            "productName": f"产品 {index}",
            "propertiesValue": f"规格 {index}",
            "quantity": index,
            "imageObjectKey": None,
        }
        for index in (1, 2)
    ]

    sheet = load_workbook(BytesIO(renderer.render(_snapshot(lines))))["合同"]

    for row in (8, 9):
        for column in (1, 2, 3):
            cell = sheet.cell(row, column)
            assert cell.style_id != 0
            assert cell.border.left.style == "thin"
            assert cell.border.right.style == "thin"
            assert cell.border.bottom.style == "thin"
