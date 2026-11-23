"""共享的 UTC 日期窗解析（半开区间 [from 00:00, to+1d 00:00)）。

驾驶舱（Q92）与 Q44 目的配比健康度共用同一口径；默认近 30 天（含今天）。
"""

from datetime import UTC, date, datetime, time, timedelta

WINDOW_DEFAULT_DAYS = 30


class TimeWindowInvalid(ValueError):
    """时间窗非法（from 晚于 to）。"""


def default_window(today: date | None = None) -> tuple[date, date]:
    today = today or datetime.now(UTC).date()
    return today - timedelta(days=WINDOW_DEFAULT_DAYS - 1), today


def window_bounds(
    date_from: date | None, date_to: date | None
) -> tuple[datetime, datetime]:
    if date_from is None or date_to is None:
        d_from, d_to = default_window()
        date_from = date_from or d_from
        date_to = date_to or d_to
    if date_from > date_to:
        raise TimeWindowInvalid("date_from must be on or before date_to")
    start = datetime.combine(date_from, time.min, tzinfo=UTC)
    end = datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=UTC)
    return start, end
