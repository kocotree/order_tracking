import re

_SUFFIX_SIZE = re.compile(r"^(.+?[\u4e00-\u9fff])(XXXL|XXL|XL|XS|S|M|L|F|均码|无尺码|\d{2,3})$")


def extract_color(properties_value: str) -> str | None:
    value = properties_value.strip()
    if not value:
        return None
    compound_size = re.fullmatch(r"(.+?[\u4e00-\u9fff])\d{2,3}/\d{2,3}[A-Z]?", value)
    if compound_size:
        return compound_size.group(1)
    for delimiter in (r"[;；]", r"[,，]", r"[/／]"):
        if re.search(delimiter, value):
            parts = re.split(delimiter, value)
            if len(parts) != 2:
                return None
            color, size = (part.strip() for part in parts)
            return color if color and (size or delimiter == r"[;；]") else None
    match = _SUFFIX_SIZE.fullmatch(value)
    if match:
        return match.group(1)
    if re.fullmatch(r"[\u4e00-\u9fff]+", value):
        return value
    return None
