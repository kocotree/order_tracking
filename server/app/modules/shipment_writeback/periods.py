import calendar
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

SHANGHAI = ZoneInfo("Asia/Shanghai")
START = datetime(2026, 10, 6, tzinfo=SHANGHAI).astimezone(UTC)


@dataclass(frozen=True)
class Stage:
    first: date
    last: date
    midnight_start: bool = False
    midnight_end: bool = False

    @property
    def name(self) -> str:
        return f"{self.first:%y.%m.%d}-{self.last:%m.%d}出货"

    @property
    def key(self) -> str:
        return self.first.isoformat()

    @property
    def since(self) -> datetime:
        if self.midnight_start:
            return datetime.combine(self.first, time.min, SHANGHAI).astimezone(UTC)
        return max(START, datetime.combine(
            self.first - timedelta(days=1), time(22), SHANGHAI,
        ).astimezone(UTC))

    @property
    def until(self) -> datetime:
        if self.midnight_end:
            return datetime.combine(
                self.last + timedelta(days=1), time.min, SHANGHAI,
            ).astimezone(UTC)
        return datetime.combine(self.last, time(22), SHANGHAI).astimezone(UTC)


def month_stages(
    year: int, month: int, *, midnight_from: date | None = None,
) -> list[Stage]:
    stages = _month_stages(year, month)
    if midnight_from is None:
        return stages
    return [
        replace(stage, midnight_start=stage.first > midnight_from,
                midnight_end=stage.first >= midnight_from)
        for stage in stages
    ]


def _month_stages(year: int, month: int) -> list[Stage]:
    if (year, month) < (2026, 10):
        raise ValueError("shipment_writeback_before_takeover")
    if (year, month) == (2026, 10):
        return [Stage(date(year, month, start), date(year, month, end))
                for start, end in ((6, 11), (12, 18), (19, 25), (26, 31))]
    first = date(year, month, 1)
    last = date(year, month, calendar.monthrange(year, month)[1])
    ranges = []
    while first <= last:
        end = min(last, first + timedelta(days=6 - first.weekday()))
        ranges.append(Stage(first, end))
        first = end + timedelta(days=1)
    if (ranges[0].last - ranges[0].first).days < 2:
        ranges[:2] = [Stage(ranges[0].first, ranges[1].last)]
    if (ranges[-1].last - ranges[-1].first).days < 2:
        ranges[-2:] = [Stage(ranges[-2].first, ranges[-1].last)]
    return ranges
