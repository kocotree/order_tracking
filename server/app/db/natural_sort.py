"""MySQL natural Chinese ordering for administrator list projections.

Build keys from complete text before LIMIT. Numeric runs compare by magnitude,
with leading zeroes equal, while text uses MySQL's Chinese UCA weights. Separate
weight levels keep case/accent differences behind the whole primary string.
"""

from typing import Any

from sqlalchemy import String, case, cast, func, literal, select
from sqlalchemy.sql import ColumnElement, Select
from sqlalchemy.sql.selectable import CTE


def natural_sort_keys(source: Select[Any], *, name: str) -> CTE:
    """Accept a projection with unique ``id`` and non-null string ``value`` columns.

    The resulting CTE exposes id/key for a database JOIN + ORDER BY. The caller
    retains its original stable tie breaker. No source records leave MySQL.
    """
    values = source.cte(f"{name}_values")
    parts = select(
        values.c.id,
        values.c.value.label("rest"),
        cast(literal(""), String(4194304)).label("primary_key"),
        cast(literal(""), String(4194304)).label("secondary_key"),
        cast(literal(""), String(4194304)).label("tertiary_key"),
    ).cte(f"{name}_parts", recursive=True)
    token = func.regexp_substr(parts.c.rest, "^[0-9]+|^[^0-9]+")
    numeric = func.regexp_like(token, "^[0-9]")
    digits = func.coalesce(func.nullif(func.regexp_replace(token, "^0+", ""), ""), "0")
    weights = func.hex(func.weight_string(token.collate("utf8mb4_zh_0900_as_cs")))
    primary = func.substring_index(weights, "0000", 1)
    secondary = func.substring_index(func.substring_index(weights, "0000", 2), "0000", -1)
    tertiary = func.substring_index(weights, "0000", -1)
    number_key = func.concat("1C3D", func.lpad(func.char_length(digits), 8, "0"), digits, "!")
    parts = parts.union_all(
        select(
            parts.c.id,
            func.substring(parts.c.rest, func.char_length(token) + 1),
            func.concat(parts.c.primary_key, case((numeric, number_key), else_=primary)),
            func.concat(parts.c.secondary_key, case((numeric, "0020"), else_=secondary)),
            func.concat(parts.c.tertiary_key, case((numeric, "0002"), else_=tertiary)),
        ).where(parts.c.rest != "")
    )
    key: ColumnElement[Any] = func.concat(
        parts.c.primary_key,
        "!",
        parts.c.secondary_key,
        "!",
        parts.c.tertiary_key,
    ).collate("utf8mb4_0900_bin")
    return select(parts.c.id, key.label("sort_key")).where(parts.c.rest == "").cte(name)
