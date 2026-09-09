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
    raw = source.cte(f"{name}_raw")
    # Intl numeric collation also recognizes Unicode decimal digits (e.g. fullwidth).
    # Only those uncommon values enter normalization; ordinary text is unchanged.
    needs_normalization = func.regexp_like(raw.c.value, r"[\p{Nd}&&[^0-9]]")
    normalized = select(
        raw.c.id,
        case((needs_normalization, raw.c.value), else_="").label("rest"),
        cast(case((needs_normalization, ""), else_=raw.c.value), String(4194304)).label("value"),
    ).cte(f"{name}_normalized", recursive=True)
    digit_or_text = func.regexp_substr(normalized.c.rest, r"^\p{Nd}|^[^\p{Nd}]+")
    ordinal = func.ord(digit_or_text)
    # UTF-8 decimal blocks are consecutive, including their byte representation.
    zero_ordinals = [
        48,
        55712,
        56240,
        57216,
        14722470,
        14722982,
        14723494,
        14724006,
        14724518,
        14725030,
        14725542,
        14726054,
        14726566,
        14727078,
        14727568,
        14728080,
        14728352,
        14778752,
        14779024,
        14786464,
        14786704,
        14787974,
        14788496,
        14789248,
        14789264,
        14790032,
        14790320,
        14791040,
        14791056,
        15374496,
        15377296,
        15377536,
        15378320,
        15378352,
        15378832,
        15380400,
        15711376,
        4036006560,
        4036015280,
        4036067750,
        4036068272,
        4036068534,
        4036069264,
        4036070320,
        4036071824,
        4036072336,
        4036073872,
        4036074368,
        4036074672,
        4036076448,
        4036076944,
        4036080016,
        4036081040,
        4036081312,
        4036405664,
        4036406672,
        4036861838,
        4036861848,
        4036861858,
        4036861868,
        4036861878,
        4036920704,
        4036922288,
        4036928912,
        4036997040,
    ]
    normalized_token = case(
        *[
            (ordinal.between(zero, zero + 9), cast(ordinal - zero, String()))
            for zero in zero_ordinals
        ],
        else_=digit_or_text,
    )
    normalized = normalized.union_all(
        select(
            normalized.c.id,
            func.substring(normalized.c.rest, func.char_length(digit_or_text) + 1),
            func.concat(normalized.c.value, normalized_token),
        ).where(normalized.c.rest != "")
    )
    values = (
        select(normalized.c.id, normalized.c.value)
        .where(normalized.c.rest == "")
        .cte(f"{name}_values")
    )
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
