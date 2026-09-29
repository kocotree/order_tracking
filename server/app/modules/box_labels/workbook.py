from io import BytesIO
from zipfile import ZipFile

from PIL import Image
from xlsxwriter import Workbook


class BoxLabelWorkbookRenderer:
    def render(self, values: dict[str, str], image: bytes | None) -> bytes:
        image_data: bytes | None = None
        image_name = "product.png"
        if image is not None:
            if len(image) > 5 * 1024 * 1024:
                raise ValueError("product image is too large")
            with Image.open(BytesIO(image)) as source:
                source.load()
                width, height = source.size
                if width <= 0 or height <= 0 or width > 6000 or height > 6000:
                    raise ValueError("invalid product image size")
                if source.format in {"PNG", "JPEG", "GIF"}:
                    image_data = image
                    image_name = f"product.{source.format.lower().replace('jpeg', 'jpg')}"
                else:
                    converted = BytesIO()
                    source.save(converted, format="PNG")
                    image_data = converted.getvalue()

        output = BytesIO()
        workbook = Workbook(output, {"in_memory": True})
        sheet = workbook.add_worksheet("1")
        sheet.set_column("A:A", 29.0982142857143)
        sheet.set_column("B:B", 11.2678571428571)
        sheet.set_column("C:C", 8.52678571428571)
        sheet.set_column("D:E", 9)
        sheet.set_default_row(31)
        sheet.set_paper(9)
        sheet.set_portrait()
        sheet.fit_to_pages(1, 1)
        sheet.set_margins(0.75, 0.75, 1, 1)
        sheet.print_area("A1:E18")
        image_format = workbook.add_format({
            "font_name": "宋体", "font_size": 12, "align": "center",
            "valign": "vcenter", "border": 1,
        })
        field_format = workbook.add_format({
            "font_name": "宋体", "font_size": 12, "align": "left",
            "valign": "vcenter", "border": 1,
        })
        labels = (
            ("factory", "工厂"), ("itemNo", "货号"),
            ("productName", "品名"), ("color", "颜色"),
        )
        for start in (1, 11):
            sheet.write(f"A{start}", "产品图片", image_format)
            sheet.merge_range(f"A{start + 1}:A{start + 7}", "", image_format)
            for offset, (key, label) in enumerate(labels):
                sheet.merge_range(
                    f"B{start + offset}:E{start + offset}",
                    f"{label}：{values[key]}", field_format,
                )
            for offset, label in ((4, "尺码"), (5, "装箱数量")):
                row = start + offset
                for column in "BCDE":
                    sheet.write_blank(f"{column}{row}", None, field_format)
                sheet.write(f"B{row}", f"{label}：", field_format)
            for offset, label in ((6, "发货日期"), (7, "箱号/总箱数")):
                row = start + offset
                sheet.merge_range(f"B{row}:E{row}", f"{label}：", field_format)
            if image_data is not None:
                sheet.embed_image(
                    f"A{start + 1}", image_name,
                    {"image_data": BytesIO(image_data), "cell_format": image_format},
                )
        workbook.close()
        content = output.getvalue()
        if image_data is None:
            return content
        # XlsxWriter 3.2.9 内存模式多写了路径前导斜杠，WPS 因此忽略单元格图片。
        incorrect = "/xl/richData/_rels/richValueRel.xml.rels"
        with ZipFile(BytesIO(content)) as package:
            if incorrect not in package.namelist():
                return content
            repaired = BytesIO()
            with ZipFile(repaired, "w") as output_package:
                for member in package.infolist():
                    if member.filename == incorrect:
                        member.filename = incorrect[1:]
                    output_package.writestr(member, package.read(member))
        return repaired.getvalue()
