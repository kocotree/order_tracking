from collections.abc import Iterable

PRODUCT_CATEGORIES = (
    "童帽春夏", "童配春夏", "童装春夏",
    "童帽秋冬", "童配秋冬", "童装秋冬", "儿童手套",
)
PRODUCT_CATEGORY_ALLOWLIST = frozenset(PRODUCT_CATEGORIES)


def category_summary(values: Iterable[str | None]) -> str | None:
    categories = {value.strip() for value in values if value and value.strip()}
    ordered = [value for value in PRODUCT_CATEGORIES if value in categories]
    ordered.extend(sorted(categories - PRODUCT_CATEGORY_ALLOWLIST))
    return "、".join(ordered) or None
