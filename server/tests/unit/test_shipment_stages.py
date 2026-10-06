from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.modules.shipment_writeback.periods import month_stages


def test_november_merges_both_short_fragments_and_carries_previous_cutoff() -> None:
    stages = month_stages(2026, 11)
    assert [stage.name for stage in stages] == [
        "26.11.01-11.08出货", "26.11.09-11.15出货",
        "26.11.16-11.22出货", "26.11.23-11.30出货",
    ]
    shanghai = ZoneInfo("Asia/Shanghai")
    assert stages[0].since.astimezone(shanghai) == datetime(2026, 10, 31, 22, tzinfo=shanghai)
    assert stages[0].until.astimezone(shanghai) == datetime(2026, 11, 8, 22, tzinfo=shanghai)
    assert stages[1].since == stages[0].until


@pytest.mark.parametrize(("year", "month", "days"), [
    (2026, 10, [(6, 11), (12, 18), (19, 25), (26, 31)]),
    (2027, 1, [(1, 3), (4, 10), (11, 17), (18, 24), (25, 31)]),
    (2027, 5, [(1, 9), (10, 16), (17, 23), (24, 31)]),
    (2027, 6, [(1, 6), (7, 13), (14, 20), (21, 27), (28, 30)]),
    (2028, 2, [(1, 6), (7, 13), (14, 20), (21, 29)]),
])
def test_takeover_and_calendar_examples(
    year: int, month: int, days: list[tuple[int, int]],
) -> None:
    stages = month_stages(year, month)
    assert [(stage.first.day, stage.last.day) for stage in stages] == days
    assert all(left.until == right.since for left, right in zip(stages, stages[1:], strict=False))
