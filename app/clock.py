"""Time helpers. All calendar times are stored as local (naive) datetimes in TIMEZONE."""
from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.config import TIMEZONE


def now_local() -> datetime:
    return datetime.now(ZoneInfo(TIMEZONE)).replace(tzinfo=None, microsecond=0)


def today_local() -> date:
    return now_local().date()


def parse_dt(value: str) -> datetime:
    """Accepts '2026-11-12 14:00', '2026-11-12T14:00' or '2026-11-12'."""
    return datetime.fromisoformat(value.strip().replace("T", " "))


def parse_date(value: str | None) -> date:
    return date.fromisoformat(value.strip()[:10]) if value else today_local()


def fmt_dt(dt: datetime) -> str:
    return dt.strftime("%a %d %b %H:%M")
