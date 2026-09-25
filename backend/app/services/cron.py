"""5 段式 cron 表达式解析（分 时 日 月 周），只依赖标准库。

定时配置的时间可以写「每天 08:00」这样的 `HH:MM`，也可以直接写 cron：
`0 8,18 * * *`（每天 8 点与 18 点各一次）、`*/30 * * * *`（每半小时）、
`0 8 * * 1-5`（工作日 8 点）。这里负责解析、匹配与「下一次 / 上一次触发点」的计算，
时间语义与标准 cron 一致：日与周两个字段都不是 `*` 时，满足其中一个就算命中。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta

# 各字段取值范围：分 0-59、时 0-23、日 1-31、月 1-12、周 0-7（0 与 7 都表示周日）
MINUTE_RANGE = (0, 59)
HOUR_RANGE = (0, 23)
DAY_RANGE = (1, 31)
MONTH_RANGE = (1, 12)
WEEKDAY_RANGE = (0, 7)
FIELD_LABELS = ("分", "时", "日", "月", "周")
WEEKDAY_NAMES = {
    "sun": 0,
    "mon": 1,
    "tue": 2,
    "wed": 3,
    "thu": 4,
    "fri": 5,
    "sat": 6,
}
MONTH_NAMES = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}
WEEKDAY_LABELS = ("周日", "周一", "周二", "周三", "周四", "周五", "周六")
MAX_DAYS_AHEAD = 366 * 5
CRON_FORMAT_HINT = "cron 表达式应为 5 段：分 时 日 月 周，例如 0 8 * * 1-5"


class CronError(ValueError):
    """cron 表达式不合法；继承 ValueError，接口层会直接转成 400。"""


@dataclass(frozen=True)
class CronSpec:
    """解析后的 cron：集合为 None 表示该字段是 `*`（不限制）。"""

    text: str
    minutes: frozenset[int]
    hours: frozenset[int]
    days: frozenset[int] | None
    months: frozenset[int] | None
    weekdays: frozenset[int] | None
    slots: tuple[tuple[int, int], ...]

    def matches(self, moment: datetime) -> bool:
        if moment.minute not in self.minutes or moment.hour not in self.hours:
            return False
        if self.months is not None and moment.month not in self.months:
            return False
        return self.day_matches(moment.date())

    def day_matches(self, day: date) -> bool:
        if self.days is None and self.weekdays is None:
            return True
        day_ok = self.days is None or day.day in self.days
        weekday = (day.weekday() + 1) % 7
        weekday_ok = self.weekdays is None or weekday in self.weekdays
        if self.days is None or self.weekdays is None:
            return day_ok and weekday_ok
        # 标准 cron：日与周都限定时满足其一即可
        return day_ok or weekday_ok

    def next_after(self, moment: datetime) -> datetime:
        """严格晚于 moment 的最近触发点（保留 moment 的时区）。"""
        cursor = moment.replace(second=0, microsecond=0) + timedelta(minutes=1)
        for _ in range(MAX_DAYS_AHEAD):
            if self.day_matches(cursor.date()):
                for hour, minute in self.slots:
                    candidate = cursor.replace(hour=hour, minute=minute)
                    if candidate >= cursor:
                        return candidate
            cursor = cursor.replace(hour=0, minute=0) + timedelta(days=1)
        raise CronError("未来 5 年内没有匹配到这个 cron 表达式")

    def latest_at_or_before(self, moment: datetime) -> datetime | None:
        """不晚于 moment 的最近触发点；找不到时返回 None。"""
        limit = moment.replace(second=0, microsecond=0)
        if self.matches(limit):
            return limit
        day_start = limit.replace(hour=0, minute=0)
        first_day = True
        for _ in range(MAX_DAYS_AHEAD):
            if self.day_matches(day_start.date()):
                for hour, minute in reversed(self.slots):
                    candidate = day_start.replace(hour=hour, minute=minute)
                    if not first_day or candidate < limit:
                        return candidate
            first_day = False
            day_start -= timedelta(days=1)
        return None


def _parse_field(
    text: str,
    low: int,
    high: int,
    label: str,
    *,
    names: dict[str, int] | None = None,
    wildcard_none: bool = False,
) -> frozenset[int] | None:
    raw = (text or "").strip().lower()
    if not raw:
        raise CronError(f"cron {label} 段不能为空；{CRON_FORMAT_HINT}")
    if raw == "*":
        if wildcard_none:
            return None
        return frozenset(range(low, high + 1))
    values: set[int] = set()
    for piece in raw.split(","):
        values |= _parse_piece(piece.strip(), low, high, label, names)
    if not values:
        raise CronError(f"cron {label} 段格式不对：{text}")
    return frozenset(values)


def _parse_piece(
    piece: str,
    low: int,
    high: int,
    label: str,
    names: dict[str, int] | None,
) -> set[int]:
    if not piece:
        raise CronError(f"cron {label} 段里有空项，请检查逗号分隔")
    body = piece
    step = 1
    if "/" in piece:
        body, _, tail = piece.partition("/")
        body = body.strip()
        if not tail.strip().isdigit() or int(tail) <= 0:
            raise CronError(f"cron {label} 段的步长要写成正整数，例如 */5：{piece}")
        step = int(tail.strip())
    if body in ("", "*"):
        start, end = low, high
    elif "-" in body:
        left, _, right = body.partition("-")
        start = _field_value(left, low, high, label, names)
        end = _field_value(right, low, high, label, names)
        if end < start:
            raise CronError(f"cron {label} 段的范围要从小到大：{piece}")
    else:
        start = _field_value(body, low, high, label, names)
        end = high if step > 1 else start
    return set(range(start, end + 1, step))


def _field_value(
    token: str,
    low: int,
    high: int,
    label: str,
    names: dict[str, int] | None,
) -> int:
    text = (token or "").strip().lower()
    if names and text in names:
        return names[text]
    if not re.fullmatch(r"\d+", text):
        raise CronError(f"cron {label} 段只支持数字、* 、范围和步长：{token}")
    value = int(text)
    if value < low or value > high:
        raise CronError(f"cron {label} 段取值要在 {low}-{high} 之间：{token}")
    return value


def parse_cron(value: str) -> CronSpec:
    parts = " ".join((value or "").split()).split(" ")
    if len(parts) != 5:
        raise CronError(CRON_FORMAT_HINT)
    minute_text, hour_text, day_text, month_text, weekday_text = parts
    minutes = _parse_field(minute_text, *MINUTE_RANGE, FIELD_LABELS[0])
    hours = _parse_field(hour_text, *HOUR_RANGE, FIELD_LABELS[1])
    days = _parse_field(day_text, *DAY_RANGE, FIELD_LABELS[2], wildcard_none=True)
    months = _parse_field(
        month_text,
        *MONTH_RANGE,
        FIELD_LABELS[3],
        names=MONTH_NAMES,
        wildcard_none=True,
    )
    weekdays = _parse_field(
        weekday_text,
        *WEEKDAY_RANGE,
        FIELD_LABELS[4],
        names=WEEKDAY_NAMES,
        wildcard_none=True,
    )
    if weekdays is not None:
        weekdays = frozenset(0 if item == 7 else item for item in weekdays)
    return CronSpec(
        text=" ".join(parts),
        minutes=minutes or frozenset(),
        hours=hours or frozenset(),
        days=days,
        months=months,
        weekdays=weekdays,
        slots=tuple(
            (hour, minute) for hour in sorted(hours or ()) for minute in sorted(minutes or ())
        ),
    )


def _numbers_text(values: list[int]) -> str:
    if len(values) > 8:
        return "、".join(str(item) for item in values[:8]) + " 等"
    return "、".join(str(item) for item in values)


def _minutes_text(minutes: frozenset[int]) -> str:
    values = sorted(minutes)
    if len(values) > 1 and values == list(range(values[0], values[-1] + 1)):
        return f"{values[0]}-{values[-1]} 分"
    if len(values) == 1:
        return f"{values[0]} 分"
    return f"{_numbers_text(values)} 分"


def _hours_text(hours: list[int]) -> str:
    """小时连着排（例如 9-18）时说成范围，比「9、10、…等」更好读。"""
    if len(hours) > 1 and hours == list(range(hours[0], hours[-1] + 1)):
        return f"{hours[0]}-{hours[-1]}"
    return _numbers_text(hours)


def _weekdays_text(weekdays: frozenset[int]) -> str:
    values = sorted(weekdays)
    if len(values) > 1 and values == list(range(values[0], values[-1] + 1)):
        return f"每周{WEEKDAY_LABELS[values[0]][1:]}至{WEEKDAY_LABELS[values[-1]]}"
    return "每" + "、".join(WEEKDAY_LABELS[item] for item in values)


def _day_text(spec: CronSpec) -> str:
    if spec.days is None and spec.weekdays is None:
        return ""
    if spec.days is None:
        return _weekdays_text(spec.weekdays or frozenset())
    day_part = f"每月 {_numbers_text(sorted(spec.days))} 日"
    if spec.weekdays is None:
        return day_part
    return f"{day_part}或{_weekdays_text(spec.weekdays)}"


def _clock_text(spec: CronSpec) -> str:
    minutes_all = len(spec.minutes) == 60
    hours_all = len(spec.hours) == 24
    if minutes_all and hours_all:
        return "每分钟"
    if hours_all:
        return f"每小时 {_minutes_text(spec.minutes)}"
    hours = sorted(spec.hours)
    if len(spec.minutes) == 1:
        exact = sorted(spec.minutes)[0]
        if len(hours) == 1:
            return f"{hours[0]:02d}:{exact:02d}"
        return f"{_hours_text(hours)} 点的 {exact:02d} 分"
    return f"{_hours_text(hours)} 点的 {_minutes_text(spec.minutes)}"


def describe_cron(spec: CronSpec) -> str:
    """把 cron 表达式说成人话，设置页用它告诉用户「到底什么时候跑」。"""
    clock = _clock_text(spec)
    day_part = _day_text(spec)
    if spec.months is None:
        head = day_part or "每天"
    elif spec.days is not None:
        head = f"每年 {_numbers_text(sorted(spec.months))} 月的 {_numbers_text(sorted(spec.days))} 日"
    else:
        head = f"每年 {_numbers_text(sorted(spec.months))} 月" + (day_part or "每天")
    if clock == "每分钟":
        return "每分钟" if head == "每天" else f"{head}每分钟"
    if clock.startswith("每小时"):
        return clock if head == "每天" else f"{head}{clock}"
    return f"{head} {clock}"
