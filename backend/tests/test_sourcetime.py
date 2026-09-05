from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from app.services.sourcetime import file_created_at, parse_source_datetime, pick_source_datetime

SHANGHAI = ZoneInfo("Asia/Shanghai")


def test_parse_unix_and_local_string():
    stamp = int(datetime(2026, 8, 13, 4, 0, tzinfo=timezone.utc).timestamp())
    utc = parse_source_datetime(stamp)
    assert utc is not None
    assert utc.tzinfo is not None
    milli = parse_source_datetime(stamp * 1000)
    assert milli == utc
    local = parse_source_datetime("2026-08-13 20:00:00")
    assert local is not None
    assert local.astimezone(SHANGHAI).hour == 20
    assert parse_source_datetime(613) is None
    assert parse_source_datetime("...") is None


def test_pick_source_datetime_prefers_known_keys():
    picked = pick_source_datetime(
        {
            "title": "课",
            "duration": 613,
            "pubdate": int(datetime(2026, 8, 13, 4, 0, tzinfo=timezone.utc).timestamp()),
        }
    )
    assert picked is not None
    assert picked.astimezone(SHANGHAI).month == 8
    assert picked.astimezone(SHANGHAI).day == 13


def test_file_created_at_reads_mtime(tmp_path):
    media = tmp_path / "talk.mp4"
    media.write_bytes(b"fake")
    stamp = file_created_at(media)
    assert stamp is not None
    assert stamp.tzinfo is not None
