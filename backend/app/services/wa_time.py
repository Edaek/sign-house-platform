"""WA / WhatsApp bot: UTC instants in Mongo, Hong Kong for display and calendar boundaries."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

HK = ZoneInfo('Asia/Hong_Kong')
_WEEKDAY_ZH = '一二三四五六日'


def wa_now() -> datetime:
    """Naive UTC — canonical storage for WA records, pool, status history."""
    return datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)


def wa_now_hk() -> datetime:
    """Timezone-aware now in Hong Kong."""
    return datetime.now(HK)


def hk_date_today() -> date:
    return wa_now_hk().date()


def hk_datetime_display(*, include_time: bool = True) -> str:
    dt = wa_now_hk()
    wd = _WEEKDAY_ZH[dt.weekday()]
    if include_time:
        return f'{dt.strftime("%Y-%m-%d %H:%M:%S")}（香港時間，星期{wd}）'
    return f'{dt.date().isoformat()}（星期{wd}）'


def hk_calendar_day_bounds_utc_naive(day: Optional[date] = None) -> tuple[datetime, datetime]:
    """Inclusive start, exclusive end in UTC naive for Mongo createdAt queries."""
    d = day or hk_date_today()
    start_hk = datetime(d.year, d.month, d.day, 0, 0, 0, tzinfo=HK)
    end_hk = start_hk + timedelta(days=1)
    return (
        start_hk.astimezone(timezone.utc).replace(tzinfo=None),
        end_hk.astimezone(timezone.utc).replace(tzinfo=None),
    )


def hk_day_start_utc_naive(day: Optional[date] = None) -> datetime:
    return hk_calendar_day_bounds_utc_naive(day)[0]


def parse_hk_date_range_to_utc(from_date: str, to_date: str) -> tuple[Optional[datetime], Optional[datetime]]:
    """Web search filters YYYY-MM-DD interpreted as Hong Kong calendar days."""
    start = end = None
    if from_date:
        d = date.fromisoformat(from_date[:10])
        start, _ = hk_calendar_day_bounds_utc_naive(d)
    if to_date:
        d = date.fromisoformat(to_date[:10])
        _, end = hk_calendar_day_bounds_utc_naive(d)
    return start, end


def format_api_datetime(dt: Optional[datetime]) -> Optional[str]:
    """JSON/API: always UTC with Z so clients can show Hong Kong time."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        instant = dt.replace(tzinfo=timezone.utc)
    else:
        instant = dt.astimezone(timezone.utc)
    return instant.strftime('%Y-%m-%dT%H:%M:%S') + 'Z'


def utc_naive_from_timestamp(ts: float) -> datetime:
    return datetime.fromtimestamp(ts, tz=timezone.utc).replace(tzinfo=None)
