from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from app.services.sourcetime import (
    backfill_job_source_times,
    file_created_at,
    parse_source_datetime,
    pick_html_datetime,
    pick_source_datetime,
)

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


def test_pick_source_datetime_reads_start_ts():
    # 约牛 toDetailSimple 现以 startTs（秒级 Unix）表示开播时间
    picked = pick_source_datetime({"liveName": "题材梳理课", "startTs": 1788695842})
    assert picked is not None
    assert picked.astimezone(SHANGHAI).year == 2026
    assert picked.astimezone(SHANGHAI).month == 9
    assert picked.astimezone(SHANGHAI).day == 6


def test_file_created_at_reads_mtime(tmp_path):
    media = tmp_path / "talk.mp4"
    media.write_bytes(b"fake")
    stamp = file_created_at(media)
    assert stamp is not None
    assert stamp.tzinfo is not None


def test_parse_http_and_pdf_dates():
    http = parse_source_datetime("Thu, 11 Sep 2026 07:39:00 GMT")
    assert http is not None
    assert http.astimezone(SHANGHAI).day == 11
    pdf = parse_source_datetime("D:20260911073900+08'00'")
    assert pdf is not None
    assert pdf.astimezone(SHANGHAI).hour == 7
    assert pdf.astimezone(SHANGHAI).minute == 39


def test_pick_html_datetime_from_wechat_and_nuxt():
    wechat = pick_html_datetime(
        "<script>var createTime = '2026-09-11 07:39'; var oriCreateTime = 1789083565;</script>"
    )
    assert wechat is not None
    local = wechat.astimezone(SHANGHAI)
    assert local.year == 2026
    assert local.month == 9
    assert local.day == 11
    assert local.hour == 7
    assert local.minute == 39

    nuxt = pick_html_datetime(
        'window.__NUXT__={data:[{data:{title:"盘前纪要",create_time:"2026-09-11 06:46:44"}}]}'
    )
    assert nuxt is not None
    assert nuxt.astimezone(SHANGHAI).hour == 6
    assert nuxt.astimezone(SHANGHAI).minute == 46


def test_pick_html_datetime_from_jsonld():
    html = (
        '<script type="application/ld+json">'
        '{"@type":"NewsArticle","headline":"利率会议前瞻",'
        '"datePublished":"2026-09-11T07:39:00+08:00"}'
        "</script>"
    )
    picked = pick_html_datetime(html)
    assert picked is not None
    assert picked.astimezone(SHANGHAI).hour == 7


def test_backfill_job_source_times_from_saved_html(db_session, tmp_path):
    from app.models import Job

    source = tmp_path / "source.html"
    source.write_text(
        '<p>每天十分钟阅读。</p><script>var createTime = "2026-09-11 07:39";</script>',
        encoding="utf-8",
    )
    job = Job(
        title="美股大跌！重点是...",
        source_url="https://mp.weixin.qq.com/s/example",
        source_type="web_page",
        source_path=str(source),
        status="done",
    )
    kept = Job(
        title="已有时间",
        source_url="https://example.com/a",
        source_type="web_page",
        source_path=str(source),
        source_created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        status="done",
    )
    db_session.add_all([job, kept])
    db_session.commit()
    filled = backfill_job_source_times(db_session)
    db_session.refresh(job)
    db_session.refresh(kept)
    assert job.source_created_at is not None
    from app.services.sourcetime import ensure_utc

    local = ensure_utc(job.source_created_at).astimezone(SHANGHAI)
    assert local.day == 11
    assert local.hour == 7
    assert kept.source_created_at.year == 2026
    assert kept.source_created_at.month == 1
    assert any(item[0] == job.id for item in filled)
