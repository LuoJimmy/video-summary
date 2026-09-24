from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import sessionmaker

from app.models import Job, ScheduleLog, utcnow
from app.schemas import ScheduleIn, ScheduleSiteIn
from app.services.ingest.base import CatalogItem
from app.services.schedule import load_schedule, missed_scheduled_run, seconds_until_tick
from app.services.sourcetime import SHANGHAI


def _published(days: int = 0, hour: int = 12) -> datetime:
    local = datetime.now(SHANGHAI).replace(hour=hour, minute=0, second=0, microsecond=0)
    return (local + timedelta(days=days)).astimezone(timezone.utc)


def _sites_by_adapter(client) -> dict:
    return {item["adapter"]: item for item in client.get("/api/sites").json()}


def _enable_xiaoe(client, catalog_id="appdemo", max_jobs=5, since="2026-08-01"):
    sites = _sites_by_adapter(client)
    xiaoe = sites["xiaoe"]
    payload = {
        "enabled": True,
        "time": "08:00",
        "since": since,
        "max_jobs": max_jobs,
        "domain_id": "a-share",
        "sites": [
            {"site_id": xiaoe["id"], "enabled": True, "catalog_id": catalog_id},
            {"site_id": sites["yueniu"]["id"], "enabled": False, "catalog_id": ""},
            {"site_id": sites["bilibili"]["id"], "enabled": False, "catalog_id": ""},
        ],
    }
    saved = client.put("/api/schedule", json=payload)
    assert saved.status_code == 200, saved.text
    return xiaoe, saved.json()


def test_schedule_default_and_validation(client):
    data = client.get("/api/schedule").json()
    assert data["enabled"] is False
    assert data["time"] == "08:00"
    assert data["max_jobs"] == 5
    assert data["digest_enabled"] is True
    adapters = {item["adapter"] for item in data["sites"]}
    assert adapters == {"xiaoe", "yueniu", "bilibili"}
    assert "generic" not in adapters

    sites = _sites_by_adapter(client)
    bad = client.put(
        "/api/schedule",
        json={
            "enabled": True,
            "time": "08:00",
            "since": "",
            "max_jobs": 5,
            "sites": [{"site_id": sites["xiaoe"]["id"], "enabled": True, "catalog_id": ""}],
        },
    )
    assert bad.status_code == 400
    assert "app_id" in bad.text


def test_schedule_skips_existing_url(client, db_session, monkeypatch):
    xiaoe, _ = _enable_xiaoe(client)
    db_session.add(
        Job(
            title="已有",
            source_url="https://appdemo.h5.xiaoeknow.com/v4/course/alive/l_old?app_id=appdemo",
            site_id=xiaoe["id"],
            status="failed",
            stage="done",
        )
    )
    db_session.commit()

    def fake_list(adapter_name, auth, catalog_id, since=None):
        assert adapter_name == "xiaoe"
        assert catalog_id == "appdemo"
        return [
            CatalogItem(
                source_url="https://appdemo.h5.xiaoeknow.com/v4/course/alive/l_old?app_id=appdemo",
                title="旧课",
                created_at=_published(),
            ),
            CatalogItem(
                source_url="https://appdemo.h5.xiaoeknow.com/v4/course/alive/l_new?app_id=appdemo",
                title="新课",
                created_at=_published(),
            ),
        ]

    monkeypatch.setattr("app.services.schedule.list_catalog", fake_list)
    log = client.post("/api/schedule/run").json()
    assert log["trigger"] == "manual"
    assert log["status"] == "ok"
    assert log["detail"][0]["created"] == 1
    assert log["detail"][0]["skipped"] == 1
    jobs = client.get("/api/jobs").json()["items"]
    urls = {item["source_url"] for item in jobs}
    assert "https://appdemo.h5.xiaoeknow.com/v4/course/alive/l_new?app_id=appdemo" in urls
    logs = client.get("/api/schedule/logs").json()
    assert logs[0]["id"] == log["id"]
    cleared = client.delete("/api/schedule/logs")
    assert cleared.status_code == 200
    assert client.get("/api/schedule/logs").json() == []


def test_catalog_item_exists_matches_xiaoe_short_link():
    from app.services.schedule import CatalogExistsIndex, catalog_item_exists, remember_catalog_item

    index = CatalogExistsIndex()
    remember_catalog_item(
        index,
        "https://etrsz.xetslk.com/sl/3NFDU8",
        "9.10行情梳理",
        datetime(2026, 9, 10, 11, 30),
    )
    remember_catalog_item(
        index,
        "https://etrsz.xetslk.com/sl/1uhCMi",
        "一周行情梳理",
        datetime(2026, 9, 6, 11, 30),
    )
    remember_catalog_item(
        index,
        "https://etrsz.xetslk.com/sl/TLb2f",
        "一周行情梳理",
        datetime(2026, 8, 23, 11, 30),
    )
    assert catalog_item_exists(
        index,
        "https://appdemo.h5.xiaoeknow.com/v4/course/alive/l_old?app_id=appdemo",
        "9.10行情梳理",
        datetime(2026, 9, 10, 11, 30, tzinfo=timezone.utc),
    )
    assert catalog_item_exists(
        index,
        "https://appdemo.h5.xiaoeknow.com/v4/course/alive/l_week?app_id=appdemo",
        "一周行情梳理",
        datetime(2026, 9, 6, 11, 30, tzinfo=timezone.utc),
    )
    assert not catalog_item_exists(
        index,
        "https://appdemo.h5.xiaoeknow.com/v4/course/alive/l_new?app_id=appdemo",
        "9.15行情梳理",
        datetime(2026, 9, 15, 11, 30, tzinfo=timezone.utc),
    )
    assert not catalog_item_exists(
        index,
        "https://appdemo.h5.xiaoeknow.com/v4/course/alive/l_week2?app_id=appdemo",
        "一周行情梳理",
        datetime(2026, 9, 13, 11, 30, tzinfo=timezone.utc),
    )
    remember_catalog_item(
        index,
        "https://etrsz.xetslk.com/sl/veJnp",
        "8.31 9月可能的主线梳理",
        datetime(2026, 8, 30, 16, 0),
    )
    assert catalog_item_exists(
        index,
        "https://appdemo.h5.xiaoeknow.com/v4/course/alive/l_topic?app_id=appdemo",
        "9月可能的主线梳理",
        datetime(2026, 8, 31, 11, 30, tzinfo=timezone.utc),
    )
    remember_catalog_item(
        index,
        "https://appdemo.h5.xiaoeknow.com/v4/course/alive/l_abc?app_id=appdemo",
        "资源课",
    )
    assert catalog_item_exists(
        index,
        "https://appdemo.mp.xiaoeknow.com/v4/course/alive/l_abc",
        "别名",
    )


def test_schedule_skips_xiaoe_short_link_by_title_date(client, db_session, monkeypatch):
    xiaoe, _ = _enable_xiaoe(client)
    db_session.add(
        Job(
            title="9.10行情梳理",
            source_url="https://etrsz.xetslk.com/sl/3NFDU8",
            source_created_at=_published().replace(tzinfo=None),
            site_id=xiaoe["id"],
            status="done",
            stage="done",
        )
    )
    db_session.commit()

    def fake_list(adapter_name, auth, catalog_id, since=None):
        return [
            CatalogItem(
                source_url="https://appdemo.h5.xiaoeknow.com/v4/course/alive/l_old?app_id=appdemo",
                title="9.10行情梳理",
                created_at=_published(),
            ),
            CatalogItem(
                source_url="https://appdemo.h5.xiaoeknow.com/v4/course/alive/l_new?app_id=appdemo",
                title="9.15卖票方法",
                created_at=_published(),
            ),
        ]

    monkeypatch.setattr("app.services.schedule.list_catalog", fake_list)
    log = client.post("/api/schedule/run").json()
    assert log["detail"][0]["created"] == 1
    assert log["detail"][0]["skipped"] == 1
    jobs = client.get("/api/jobs").json()["items"]
    urls = {item["source_url"] for item in jobs}
    assert "https://appdemo.h5.xiaoeknow.com/v4/course/alive/l_new?app_id=appdemo" in urls
    assert "https://appdemo.h5.xiaoeknow.com/v4/course/alive/l_old?app_id=appdemo" not in urls


def test_effective_schedule_since_clamps_to_today():
    from app.services.schedule import effective_schedule_since, shanghai_today_start

    now = datetime(2026, 9, 16, 18, 0, tzinfo=SHANGHAI)
    today = shanghai_today_start(now)
    assert effective_schedule_since("", now) == today
    assert effective_schedule_since("2026-08-01", now) == today
    assert effective_schedule_since("2026-09-20", now) > today


def test_schedule_since_and_max_jobs(client, monkeypatch):
    _enable_xiaoe(client, max_jobs=1, since="2026-08-13")

    def fake_list(adapter_name, auth, catalog_id, since=None):
        return [
            CatalogItem(
                source_url="https://appdemo.h5.xiaoeknow.com/v4/course/alive/l_new?app_id=appdemo",
                title="晚",
                created_at=_published(hour=20),
            ),
            CatalogItem(
                source_url="https://appdemo.h5.xiaoeknow.com/v4/course/alive/l_mid?app_id=appdemo",
                title="早",
                created_at=_published(hour=8),
            ),
            CatalogItem(
                source_url="https://appdemo.h5.xiaoeknow.com/v4/course/alive/l_old?app_id=appdemo",
                title="昨天",
                created_at=_published(-1),
            ),
        ]

    monkeypatch.setattr("app.services.schedule.list_catalog", fake_list)
    log = client.post("/api/schedule/run").json()
    assert log["detail"][0]["created"] == 1
    jobs = client.get("/api/jobs").json()["items"]
    assert [item["title"] for item in jobs] == ["晚"]


def test_schedule_only_creates_today_jobs(client, monkeypatch):
    _enable_xiaoe(client, max_jobs=5, since="2026-08-01")

    def fake_list(adapter_name, auth, catalog_id, since=None):
        assert since is not None
        return [
            CatalogItem(
                source_url="https://appdemo.h5.xiaoeknow.com/v4/course/alive/l_today?app_id=appdemo",
                title="今天",
                created_at=_published(),
            ),
            CatalogItem(
                source_url="https://appdemo.h5.xiaoeknow.com/v4/course/alive/l_yday?app_id=appdemo",
                title="昨天",
                created_at=_published(-1),
            ),
        ]

    monkeypatch.setattr("app.services.schedule.list_catalog", fake_list)
    log = client.post("/api/schedule/run").json()
    assert log["detail"][0]["created"] == 1
    jobs = client.get("/api/jobs").json()["items"]
    assert [item["title"] for item in jobs] == ["今天"]


def test_schedule_site_error_is_partial(client, monkeypatch):
    from app.services.ingest.base import CatalogError

    sites = _sites_by_adapter(client)
    client.put(
        "/api/schedule",
        json={
            "enabled": True,
            "time": "08:00",
            "since": "",
            "max_jobs": 5,
            "sites": [
                {"site_id": sites["xiaoe"]["id"], "enabled": True, "catalog_id": "appdemo"},
                {"site_id": sites["yueniu"]["id"], "enabled": True, "catalog_id": ""},
                {"site_id": sites["bilibili"]["id"], "enabled": False, "catalog_id": ""},
            ],
        },
    )

    def fake_list(adapter_name, auth, catalog_id, since=None):
        if adapter_name == "yueniu":
            raise CatalogError("未配置约牛登录 Cookie，无法拉取直播日历")
        return [
            CatalogItem(
                source_url="https://appdemo.h5.xiaoeknow.com/v4/course/alive/l_ok?app_id=appdemo",
                title="成功",
                created_at=_published(),
            )
        ]

    monkeypatch.setattr("app.services.schedule.list_catalog", fake_list)
    log = client.post("/api/schedule/run").json()
    assert log["status"] == "partial"
    assert "约牛" in log["summary"]
    assert log["detail"][0]["created"] + log["detail"][1]["created"] == 1


def test_split_catalog_ids():
    from app.services.schedule import split_catalog_ids

    assert split_catalog_ids("app1, app2\napp3") == ["app1", "app2", "app3"]
    assert split_catalog_ids("11430504，11430505") == ["11430504", "11430505"]
    assert split_catalog_ids("  ") == []


def test_schedule_summary_dedupes_rate_limit():
    from app.services.schedule import _build_summary, _join_unique

    assert _join_unique(["请求过于频繁，请稍后再试"] * 5) == "请求过于频繁，请稍后再试"
    text, status = _build_summary(
        [{"site_name": "B站", "created": 3, "skipped": 0, "listed": 8, "error": "请求过于频繁，请稍后再试"}],
        created_total=3,
        skipped_total=0,
    )
    assert status == "partial"
    assert "新建 3" in text
    assert "失败" not in text
    assert text.count("请求过于频繁") == 1
    skipped_text, skipped_status = _build_summary(
        [{"site_name": "B站", "created": 0, "skipped": 2, "listed": 2, "error": "请求过于频繁，请稍后再试"}],
        created_total=0,
        skipped_total=2,
    )
    assert skipped_status == "partial"
    assert "跳过 2" in skipped_text
    assert "失败" not in skipped_text


def test_schedule_bilibili_rate_limit_errors_are_deduped(client, monkeypatch):
    from app.services.ingest.base import CatalogError

    monkeypatch.setattr("app.services.schedule.BILI_CATALOG_PAUSE", 0)
    sites = _sites_by_adapter(client)
    saved = client.put(
        "/api/schedule",
        json={
            "enabled": True,
            "time": "08:00",
            "since": "",
            "max_jobs": 5,
            "sites": [
                {"site_id": sites["xiaoe"]["id"], "enabled": False, "catalog_id": ""},
                {"site_id": sites["yueniu"]["id"], "enabled": False, "catalog_id": ""},
                {"site_id": sites["bilibili"]["id"], "enabled": True, "catalog_id": "1,2,3,4,5"},
            ],
        },
    )
    assert saved.status_code == 200, saved.text

    def fake_list(adapter_name, auth, catalog_id, since=None):
        raise CatalogError("请求过于频繁，请稍后再试")

    monkeypatch.setattr("app.services.schedule.list_catalog", fake_list)
    log = client.post("/api/schedule/run").json()
    assert log["status"] == "failed"
    assert log["summary"].count("请求过于频繁") == 1
    assert "失败" in log["summary"]


def test_schedule_bilibili_stops_remaining_ups_after_rate_limit(client, monkeypatch):
    from app.services.ingest.base import CatalogError

    monkeypatch.setattr("app.services.schedule.BILI_CATALOG_PAUSE", 0)
    sites = _sites_by_adapter(client)
    saved = client.put(
        "/api/schedule",
        json={
            "enabled": True,
            "time": "08:00",
            "since": "",
            "max_jobs": 5,
            "sites": [
                {"site_id": sites["xiaoe"]["id"], "enabled": False, "catalog_id": ""},
                {"site_id": sites["yueniu"]["id"], "enabled": False, "catalog_id": ""},
                {"site_id": sites["bilibili"]["id"], "enabled": True, "catalog_id": "111,222,333"},
            ],
        },
    )
    assert saved.status_code == 200, saved.text
    seen: list[str] = []

    def fake_list(adapter_name, auth, catalog_id, since=None):
        seen.append(catalog_id)
        raise CatalogError("B站稿件列表被限流，请等几分钟再试")

    monkeypatch.setattr("app.services.schedule.list_catalog", fake_list)
    log = client.post("/api/schedule/run").json()
    assert seen == ["111"]
    assert log["status"] == "failed"
    assert "限流" in log["summary"]


def test_schedule_bilibili_keeps_created_jobs_when_later_up_rate_limited(client, monkeypatch):
    from app.services.ingest.base import CatalogError

    monkeypatch.setattr("app.services.schedule.BILI_CATALOG_PAUSE", 0)
    sites = _sites_by_adapter(client)
    saved = client.put(
        "/api/schedule",
        json={
            "enabled": True,
            "time": "08:00",
            "since": "",
            "max_jobs": 5,
            "sites": [
                {"site_id": sites["xiaoe"]["id"], "enabled": False, "catalog_id": ""},
                {"site_id": sites["yueniu"]["id"], "enabled": False, "catalog_id": ""},
                {"site_id": sites["bilibili"]["id"], "enabled": True, "catalog_id": "111,222"},
            ],
        },
    )
    assert saved.status_code == 200, saved.text

    def fake_list(adapter_name, auth, catalog_id, since=None):
        if catalog_id == "222":
            raise CatalogError("请求过于频繁，请稍后再试")
        return [
            CatalogItem(
                source_url="https://www.bilibili.com/video/BV1a4awzsENn",
                title="卖票方法",
                created_at=_published(),
            )
        ]

    monkeypatch.setattr("app.services.schedule.list_catalog", fake_list)
    log = client.post("/api/schedule/run").json()
    assert log["status"] == "partial"
    assert log["detail"][0]["created"] == 1
    assert "新建 1" in log["summary"]
    assert "失败" not in log["summary"]
    assert "已保留已拉到的条目" in log["summary"]
    assert "Cookie" in log["summary"]
    assert "过于频繁" not in log["summary"]


def test_schedule_hides_rate_limit_when_quota_filled(client, monkeypatch):
    from app.services.ingest.base import CatalogError

    monkeypatch.setattr("app.services.schedule.BILI_CATALOG_PAUSE", 0)
    sites = _sites_by_adapter(client)
    saved = client.put(
        "/api/schedule",
        json={
            "enabled": True,
            "time": "08:00",
            "since": "",
            "max_jobs": 1,
            "sites": [
                {"site_id": sites["xiaoe"]["id"], "enabled": False, "catalog_id": ""},
                {"site_id": sites["yueniu"]["id"], "enabled": False, "catalog_id": ""},
                {"site_id": sites["bilibili"]["id"], "enabled": True, "catalog_id": "111,222"},
            ],
        },
    )
    assert saved.status_code == 200, saved.text

    def fake_list(adapter_name, auth, catalog_id, since=None):
        if catalog_id == "222":
            raise CatalogError("稿件列表被限流，请等几分钟再试")
        return [
            CatalogItem(
                source_url="https://www.bilibili.com/video/BV1a4awzsENn",
                title="卖票方法",
                created_at=_published(),
            )
        ]

    monkeypatch.setattr("app.services.schedule.list_catalog", fake_list)
    log = client.post("/api/schedule/run").json()
    assert log["status"] == "ok"
    assert log["detail"][0]["created"] == 1
    assert "新建 1" in log["summary"]
    assert "限流" not in log["summary"]


def test_schedule_multiple_catalog_ids(client, monkeypatch):
    _enable_xiaoe(client, catalog_id="appone, apptwo")
    seen: list[str] = []

    def fake_list(adapter_name, auth, catalog_id, since=None):
        seen.append(catalog_id)
        return [
            CatalogItem(
                source_url=f"https://{catalog_id}.h5.xiaoeknow.com/v4/course/alive/{catalog_id}?app_id={catalog_id}",
                title=catalog_id,
                created_at=_published(),
            )
        ]

    monkeypatch.setattr("app.services.schedule.list_catalog", fake_list)
    log = client.post("/api/schedule/run").json()
    assert seen == ["appone", "apptwo"]
    assert log["detail"][0]["created"] == 2


def test_cannot_delete_last_xiaoe_site(client):
    sites = _sites_by_adapter(client)
    resp = client.delete(f"/api/sites/{sites['xiaoe']['id']}")
    assert resp.status_code == 400
    assert "小鹅通" in resp.text


def test_extra_xiaoe_site_appears_in_schedule(client):
    sites = _sites_by_adapter(client)
    xiaoe = sites["xiaoe"]
    created = client.post(
        "/api/sites",
        json={
            "name": "启富课堂",
            "adapter": "xiaoe",
            "domain_patterns": xiaoe["domain_patterns"],
            "auth_profile_id": xiaoe["auth_profile_id"],
            "cookie_override": "",
            "extra_headers": {},
            "enabled": True,
            "notes": "",
        },
    )
    assert created.status_code == 200, created.text
    data = client.get("/api/schedule").json()
    names = [item["name"] for item in data["sites"] if item["adapter"] == "xiaoe"]
    assert "小鹅通" in names
    assert "启富课堂" in names


def test_seconds_until_tick_and_missed_run(db_session):
    from app.models import Site
    from app.services.schedule import save_schedule

    wait = seconds_until_tick(False, "08:00")
    assert wait == 3600.0
    now = datetime(2026, 9, 10, 9, 0, tzinfo=SHANGHAI)
    assert seconds_until_tick(True, "08:00", now) > 3600
    assert missed_scheduled_run(db_session, now) is False
    xiaoe = db_session.query(Site).filter(Site.adapter == "xiaoe").one()
    save_schedule(
        db_session,
        ScheduleIn(
            enabled=True,
            time="08:00",
            since="",
            max_jobs=5,
            sites=[ScheduleSiteIn(site_id=xiaoe.id, enabled=False, catalog_id="")],
        ),
    )
    assert missed_scheduled_run(db_session, now) is True
    morning = datetime(2026, 9, 10, 7, 0, tzinfo=SHANGHAI)
    assert missed_scheduled_run(db_session, morning) is False


def test_schedule_time_is_shanghai_even_in_utc_process(db_session):
    """容器 / 进程时区是 UTC 时，18:01 仍要按北京时间解释，不能被当成 UTC 18:01。"""
    from app.models import Site
    from app.services.schedule import save_schedule

    xiaoe = db_session.query(Site).filter(Site.adapter == "xiaoe").one()
    save_schedule(
        db_session,
        ScheduleIn(
            enabled=True,
            time="18:01",
            since="",
            max_jobs=5,
            sites=[ScheduleSiteIn(site_id=xiaoe.id, enabled=False, catalog_id="")],
        ),
    )
    before = datetime(2026, 9, 23, 9, 0, tzinfo=timezone.utc)  # 北京 17:00
    assert 3659 < seconds_until_tick(True, "18:01", before) < 3662
    assert missed_scheduled_run(db_session, before) is False
    at_time = datetime(2026, 9, 23, 10, 1, tzinfo=timezone.utc)  # 北京 18:01
    assert missed_scheduled_run(db_session, at_time) is True


def test_missed_scheduled_run_ignores_skip_log(db_session):
    """「已跳过」记录不算执行过，不能挡住当天补跑。"""
    from app.models import Site
    from app.services.schedule import save_schedule

    xiaoe = db_session.query(Site).filter(Site.adapter == "xiaoe").one()
    save_schedule(
        db_session,
        ScheduleIn(
            enabled=True,
            time="18:01",
            since="",
            max_jobs=5,
            sites=[ScheduleSiteIn(site_id=xiaoe.id, enabled=False, catalog_id="")],
        ),
    )
    at_time = datetime(2026, 9, 23, 10, 1, tzinfo=timezone.utc)  # 北京 18:01
    db_session.add(
        ScheduleLog(
            trigger="cron",
            status="skipped",
            summary="今天已经执行过定时任务，本轮到点不再扫描",
            finished_at=datetime(2026, 9, 23, 10, 1),
        )
    )
    db_session.commit()
    assert missed_scheduled_run(db_session, at_time) is True


def test_run_due_tick_notes_skip_and_runs_when_due(db_session, monkeypatch):
    """到点评估：没到点不留痕；到点没跑过就扫描；当天跑过则留一条「已跳过」。"""
    from app.models import Site
    from app.services import schedule as schedule_service

    TestingSession = sessionmaker(bind=db_session.get_bind(), autoflush=False, autocommit=False)
    monkeypatch.setattr(schedule_service, "SessionLocal", TestingSession)
    monkeypatch.setattr(schedule_service, "_skip_log_day", "")
    ran: list[str] = []
    monkeypatch.setattr(schedule_service, "_safe_run_once", lambda trigger: ran.append(trigger))

    xiaoe = db_session.query(Site).filter(Site.adapter == "xiaoe").one()
    schedule_service.save_schedule(
        db_session,
        ScheduleIn(
            enabled=True,
            time="18:01",
            since="",
            max_jobs=5,
            sites=[ScheduleSiteIn(site_id=xiaoe.id, enabled=False, catalog_id="")],
        ),
    )
    before = datetime(2026, 9, 23, 9, 0, tzinfo=timezone.utc)  # 北京 17:00
    at_time = datetime(2026, 9, 23, 10, 1, tzinfo=timezone.utc)  # 北京 18:01

    db_session.rollback()
    assert schedule_service._run_due_tick("cron", before) is False
    db_session.rollback()
    assert ran == []
    assert db_session.query(ScheduleLog).count() == 0

    assert schedule_service._run_due_tick("cron", at_time) is True
    db_session.rollback()
    assert ran == ["cron"]
    assert db_session.query(ScheduleLog).count() == 0

    monkeypatch.setattr(schedule_service, "_skip_log_day", "")
    db_session.add(
        ScheduleLog(
            trigger="cron",
            status="ok",
            summary="当天已经跑过",
            finished_at=datetime(2026, 9, 23, 10, 0),
        )
    )
    db_session.commit()
    assert schedule_service._run_due_tick("cron", at_time) is False
    db_session.rollback()
    assert ran == ["cron"]
    skipped = db_session.query(ScheduleLog).filter(ScheduleLog.status == "skipped").all()
    assert len(skipped) == 1
    assert skipped[0].trigger == "cron"
    assert "已经执行过" in skipped[0].summary
    assert skipped[0].finished_at is not None


def test_cron_does_not_run_when_schedule_disabled(client, db_session, monkeypatch):
    from app.models import ScheduleLog
    from app.services.schedule import run_once

    sites = _sites_by_adapter(client)
    saved = client.put(
        "/api/schedule",
        json={
            "enabled": False,
            "time": "08:00",
            "since": "",
            "max_jobs": 5,
            "sites": [
                {"site_id": sites["xiaoe"]["id"], "enabled": False, "catalog_id": ""},
                {"site_id": sites["yueniu"]["id"], "enabled": False, "catalog_id": ""},
                {"site_id": sites["bilibili"]["id"], "enabled": True, "catalog_id": "11430504"},
            ],
        },
    )
    assert saved.status_code == 200, saved.text
    called: list[str] = []

    def fake_list(adapter_name, auth, catalog_id, since=None):
        called.append(catalog_id)
        return [
            CatalogItem(
                source_url="https://www.bilibili.com/video/BV1a4awzsENn",
                title="不应创建",
                created_at=_published(),
            )
        ]

    monkeypatch.setattr("app.services.schedule.list_catalog", fake_list)
    try:
        run_once("cron", execute=False, db=db_session)
        raise AssertionError("disabled schedule should not run")
    except ValueError as exc:
        assert "未启用" in str(exc)
    assert called == []
    assert db_session.query(ScheduleLog).count() == 0
    assert client.get("/api/jobs").json()["items"] == []


def test_cron_skips_second_run_the_same_day(client, db_session, monkeypatch):
    from app.models import ScheduleLog
    from app.services.schedule import run_once

    _enable_xiaoe(client)
    monkeypatch.setattr(
        "app.services.schedule.list_catalog",
        lambda adapter_name, auth, catalog_id, since=None: [
            CatalogItem(
                source_url="https://appdemo.h5.xiaoeknow.com/v4/course/alive/l_once?app_id=appdemo",
                title="只应创建一次",
                created_at=_published(),
            )
        ],
    )
    first = run_once("cron", execute=False, db=db_session)
    assert first.status == "ok"
    assert first.detail[0].created == 1
    assert db_session.query(ScheduleLog).count() == 1
    jobs = client.get("/api/jobs").json()["items"]
    assert len(jobs) == 1
    try:
        run_once("cron", execute=False, db=db_session)
        raise AssertionError("second cron run should skip")
    except ValueError as exc:
        assert "今日已执行" in str(exc)
    assert db_session.query(ScheduleLog).count() == 1
    assert len(client.get("/api/jobs").json()["items"]) == 1
    manual = client.post("/api/schedule/run").json()
    assert manual["trigger"] == "manual"


def test_schedule_run_binds_log_and_digest_id(client, db_session, monkeypatch):
    captured = {}

    def fake_execute(job_ids, digest_log_id=None):
        captured["ids"] = list(job_ids)
        captured["digest"] = digest_log_id

    monkeypatch.setattr("app.services.schedule._execute_jobs", fake_execute)

    def fake_list(adapter_name, auth, catalog_id, since=None):
        return [
            CatalogItem(
                source_url="https://appdemo.h5.xiaoeknow.com/v4/course/alive/l_digest?app_id=appdemo",
                title="汇总源",
                author="作者甲",
                created_at=_published(),
            )
        ]

    _enable_xiaoe(client)
    monkeypatch.setattr("app.services.schedule.list_catalog", fake_list)
    log = client.post("/api/schedule/run").json()
    jobs = db_session.query(Job).all()
    assert len(jobs) == 1
    assert jobs[0].schedule_log_id == log["id"]
    assert captured["ids"] == [jobs[0].id]
    assert captured["digest"] == log["id"]


def test_schedule_digest_disabled_skips_digest_log(client, monkeypatch):
    captured = {}

    def fake_execute(job_ids, digest_log_id=None):
        captured["digest"] = digest_log_id
        captured["ids"] = list(job_ids)

    monkeypatch.setattr("app.services.schedule._execute_jobs", fake_execute)
    sites = _sites_by_adapter(client)
    saved = client.put(
        "/api/schedule",
        json={
            "enabled": True,
            "time": "08:00",
            "since": "2026-08-01",
            "max_jobs": 5,
            "domain_id": "a-share",
            "digest_enabled": False,
            "sites": [
                {"site_id": sites["xiaoe"]["id"], "enabled": True, "catalog_id": "appdemo"},
                {"site_id": sites["yueniu"]["id"], "enabled": False, "catalog_id": ""},
                {"site_id": sites["bilibili"]["id"], "enabled": False, "catalog_id": ""},
            ],
        },
    )
    assert saved.status_code == 200
    assert saved.json()["digest_enabled"] is False

    def fake_list(adapter_name, auth, catalog_id, since=None):
        return [
            CatalogItem(
                source_url="https://appdemo.h5.xiaoeknow.com/v4/course/alive/l_off?app_id=appdemo",
                title="关闭汇总",
                created_at=_published(),
            )
        ]

    monkeypatch.setattr("app.services.schedule.list_catalog", fake_list)
    client.post("/api/schedule/run")
    assert captured["ids"]
    assert captured["digest"] is None


def test_run_created_jobs_digest_only_with_log(monkeypatch):
    from app.services.schedule import _run_created_jobs

    ran = []

    class Pipe:
        def run_job(self, job_id):
            ran.append(("job", job_id))

    monkeypatch.setattr("app.services.schedule.get_pipeline", lambda: Pipe())
    monkeypatch.setattr("app.services.digest.run_schedule_digest", lambda log_id: ran.append(("digest", log_id)))
    _run_created_jobs(["j1", "j2"], digest_log_id="log-1")
    assert ran == [("job", "j1"), ("job", "j2"), ("digest", "log-1")]
    ran.clear()
    _run_created_jobs(["j3"])
    assert ran == [("job", "j3")]


def test_start_detached_run_skips_previous_completed_log(db_session, monkeypatch):
    from app.services.schedule import start_detached_run

    TestingSession = sessionmaker(bind=db_session.get_bind(), autoflush=False, autocommit=False)
    monkeypatch.setattr("app.services.schedule.SessionLocal", TestingSession)
    old = ScheduleLog(trigger="manual", status="ok", summary="旧日志", finished_at=utcnow())
    db_session.add(old)
    db_session.commit()
    old_id = old.id

    def fake_run(trigger="manual", execute=True, db=None):
        session = TestingSession()
        try:
            row = ScheduleLog(trigger=trigger, status="running", summary="正在扫描站点")
            session.add(row)
            session.commit()
        finally:
            session.close()

    monkeypatch.setattr("app.services.schedule.run_once", fake_run)
    result = start_detached_run("manual")
    assert result.id != old_id
    assert result.status == "running"
    assert "正在扫描" in result.summary

