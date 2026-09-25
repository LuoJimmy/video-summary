from datetime import datetime, timezone

import pytest

from app.models import ScheduleLog, ScheduleRule
from app.services.cron import CronError, describe_cron, parse_cron
from app.services.schedule import (
    missed_scheduled_run,
    run_scan_since,
    seconds_until_next_tick,
    shanghai_today_start,
)
from app.services.sourcetime import SHANGHAI


def _at(day: int = 10, hour: int = 0, minute: int = 0) -> datetime:
    return datetime(2026, 9, day, hour, minute, tzinfo=SHANGHAI)


def _rule(db_session, rule_id: str, cron: str, time_text: str = "08:00") -> ScheduleRule:
    rule = ScheduleRule(id=rule_id, name=rule_id, enabled=True, time=time_text, cron=cron)
    db_session.add(rule)
    db_session.commit()
    return rule


def test_parse_cron_splits_fields():
    spec = parse_cron("0 8,18 * * *")
    assert spec.minutes == frozenset({0})
    assert spec.hours == frozenset({8, 18})
    assert spec.days is None
    assert spec.weekdays is None
    assert spec.slots == ((8, 0), (18, 0))
    assert spec.text == "0 8,18 * * *"


def test_parse_cron_step_range_and_month_names():
    step = parse_cron("*/30 9-11 * * 1-5")
    assert sorted(step.minutes) == [0, 30]
    assert sorted(step.hours) == [9, 10, 11]
    assert sorted(step.weekdays) == [1, 2, 3, 4, 5]
    assert sorted(parse_cron("5/10 * * * *").minutes) == [5, 15, 25, 35, 45, 55]
    assert sorted(parse_cron("0 8 1 jan *").months) == [1]


@pytest.mark.parametrize(
    "text",
    [
        "",
        "0 8 * *",
        "0 8 * * * *",
        "60 8 * * *",
        "0 24 * * *",
        "0 8 32 * *",
        "0 8 * 13 *",
        "0 8 * * 8",
        "0 8 * * x",
        "*/0 8 * * *",
        "18-8 9 * * *",
    ],
)
def test_parse_cron_rejects_bad_expressions(text):
    with pytest.raises(CronError):
        parse_cron(text)


def test_weekday_zero_and_seven_are_sunday():
    assert parse_cron("0 8 * * 0").weekdays == frozenset({0})
    assert parse_cron("0 8 * * 7").weekdays == frozenset({0})
    assert parse_cron("0 8 * * sun").weekdays == frozenset({0})


def test_day_and_weekday_both_set_uses_or():
    spec = parse_cron("0 8 1 * 1")
    assert spec.matches(_at(day=1, hour=8)) is True  # 每月 1 日（2026-09-01 是周二）
    assert spec.matches(_at(day=7, hour=8)) is True  # 周一（2026-09-07）
    assert spec.matches(_at(day=10, hour=8)) is False
    assert spec.matches(_at(day=1, hour=9)) is False


def test_month_field_limits_matched_days():
    spec = parse_cron("0 8 1 1 *")
    assert spec.matches(datetime(2026, 1, 1, 8, 0, tzinfo=SHANGHAI)) is True
    assert spec.matches(datetime(2026, 2, 1, 8, 0, tzinfo=SHANGHAI)) is False


def test_next_after_and_latest_at_or_before():
    spec = parse_cron("0 8,18 * * *")
    assert spec.next_after(_at(hour=9)) == _at(hour=18)
    assert spec.next_after(_at(hour=18)) == _at(day=11, hour=8)
    assert spec.next_after(_at(hour=7, minute=30)) == _at(hour=8)
    assert spec.latest_at_or_before(_at(hour=7)) == _at(day=9, hour=18)
    assert spec.latest_at_or_before(_at(hour=18)) == _at(hour=18)
    assert spec.latest_at_or_before(_at(hour=18, minute=30)) == _at(hour=18)
    assert spec.latest_at_or_before(_at(hour=8, minute=1)) == _at(hour=8)


def test_next_after_skips_weekend():
    spec = parse_cron("0 8 * * 1-5")
    assert spec.next_after(_at(day=11, hour=9)) == _at(day=14, hour=8)  # 周五 9 点 → 下周一 8 点


def test_describe_cron_reads_like_chinese():
    assert describe_cron(parse_cron("0 8 * * *")) == "每天 08:00"
    assert describe_cron(parse_cron("0 8,18 * * *")) == "每天 8、18 点的 00 分"
    assert describe_cron(parse_cron("0 8 * * 1-5")) == "每周一至周五 08:00"
    assert describe_cron(parse_cron("*/30 * * * *")) == "每小时 0、30 分"
    assert describe_cron(parse_cron("* * * * *")) == "每分钟"
    assert describe_cron(parse_cron("0 8 1 * *")) == "每月 1 日 08:00"
    assert describe_cron(parse_cron("*/15 9-18 * * *")) == "每天 9-18 点的 0、15、30、45 分"


def test_seconds_until_next_tick_follows_cron(db_session):
    rule = _rule(db_session, "rule-cron", "0 8,18 * * *")
    assert seconds_until_next_tick([rule], _at(hour=9)) == 9 * 3600.0
    assert seconds_until_next_tick([rule], _at(hour=19)) == 13 * 3600.0


def test_missed_scheduled_run_tracks_each_trigger_point(db_session):
    rule = _rule(db_session, "rule-twice", "0 8,18 * * *")
    morning = _at(hour=8, minute=5)
    assert missed_scheduled_run(db_session, rule, _at(hour=7)) is False  # 今天还没到点
    assert missed_scheduled_run(db_session, rule, morning) is True
    stamp = morning.astimezone(timezone.utc).replace(tzinfo=None)
    db_session.add(
        ScheduleLog(
            trigger="cron",
            status="ok",
            summary="",
            rule_id=rule.id,
            started_at=stamp,
            finished_at=stamp,
        )
    )
    db_session.commit()
    assert missed_scheduled_run(db_session, rule, morning) is False  # 8 点这一轮跑过了
    assert missed_scheduled_run(db_session, rule, _at(hour=18, minute=5)) is True  # 18 点照跑


def test_rule_cron_falls_back_to_daily_time(db_session):
    rule = _rule(db_session, "rule-daily", "")
    # 没填 cron 时按 time 每天跑一次，窗口从上一次触发点（昨天 08:00）算起
    assert run_scan_since(rule, "cron", _at(hour=19)) == _at(day=9, hour=8).astimezone(timezone.utc)
    assert run_scan_since(rule, "manual", _at(hour=19)) == shanghai_today_start(_at(hour=19))


def test_run_scan_since_uses_previous_trigger(db_session):
    rule = _rule(db_session, "rule-since", "0 8,18 * * *")
    evening = _at(hour=18)
    assert run_scan_since(rule, "cron", evening) == _at(hour=8).astimezone(timezone.utc)
    assert run_scan_since(rule, "manual", evening) == shanghai_today_start(evening)
