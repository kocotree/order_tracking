import re

_SUFFIX_SIZE = re.compile(r"^(.+?[\u4e00-\u9fff])(XXXL|XXL|XL|XS|S|M|L|F|均码|\d{2,3})$")


def extract_color(properties_value: str) -> str | None:
    value = properties_value.strip()
    if not value:
        return None
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
