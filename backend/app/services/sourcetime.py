from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

SHANGHAI = ZoneInfo("Asia/Shanghai")
SOURCE_TIME_KEYS = (
    "pubdate",
    "ctime",
    "zb_start_at",
    "alive_start_at",
    "start_at",
    "zb_start_time",
    "liveStartTime",
    "live_start_time",
    "startTime",
    "createTime",
    "created_at",
    "unix_time",
    "liveTime",
)
MIN_TS = datetime(2000, 1, 1, tzinfo=timezone.utc)
MAX_TS = datetime(2100, 1, 1, tzinfo=timezone.utc)


def ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _valid(value: datetime) -> datetime | None:
    utc = ensure_utc(value)
    if utc < MIN_TS or utc >= MAX_TS:
        return None
    return utc


def parse_source_datetime(value: Any) -> datetime | None:
    if value is None or value is False:
        return None
    if isinstance(value, datetime):
        return _valid(value)
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        if number > 1e12:
            number /= 1000
        try:
            return _valid(datetime.fromtimestamp(number, tz=timezone.utc))
        except (OSError, OverflowError, ValueError):
            return None
    text = str(value).strip()
    if not text:
        return None
    if re.fullmatch(r"-?\d+(\.\d+)?", text):
        return parse_source_datetime(float(text))
    normalized = text.replace("T", " ").replace("/", "-")
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    for fmt in (
        "%Y-%m-%d %H:%M:%S.%f%z",
        "%Y-%m-%d %H:%M:%S%z",
        "%Y-%m-%d %H:%M%z",
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
    ):
        try:
            parsed = datetime.strptime(normalized, fmt)
        except ValueError:
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=SHANGHAI)
        return _valid(parsed)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=SHANGHAI)
    return _valid(parsed)


def pick_source_datetime(*sources: Any) -> datetime | None:
    for source in sources:
        if source is None:
            continue
        parsed = parse_source_datetime(source)
        if parsed is not None:
            return parsed
        if not isinstance(source, dict):
            continue
        for key in SOURCE_TIME_KEYS:
            if key not in source:
                continue
            parsed = parse_source_datetime(source.get(key))
            if parsed is not None:
                return parsed
    return None


def file_created_at(path: str | Path) -> datetime | None:
    try:
        stat = Path(path).stat()
    except OSError:
        return None
    stamp = getattr(stat, "st_birthtime", None) or stat.st_mtime
    return parse_source_datetime(stamp)
