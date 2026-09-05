"""Factory code normalization shared by writes and one-time conversion."""

import re

CODE_ERROR = "工厂代码仅支持 1–32 位英文字母"


def code_prefix(value: str) -> str:
    return re.split(r"[（(\-]", value.strip(), maxsplit=1)[0].strip()


def normalize_factory_code(value: str) -> str | None:
    if not value.strip():
        return None
    prefix = code_prefix(value)
    if not re.fullmatch(r"[A-Za-z]{1,32}", prefix):
        raise ValueError(CODE_ERROR)
    return prefix.upper()
