from sqlalchemy.orm import sessionmaker

from app.models import Job, ScheduleLog
from app.schemas import AppSettingsOut, SummaryResult
from app.services.digest import (
    DIGEST_SOURCE,
    MANUAL_DIGEST_SOURCE,
    create_digest_from_jobs,
    digest_sources,
    encode_digest_source_url,
    fill_digest_job,
    related_job_refs,
    run_schedule_digest,
    summarize_digest,
)
from app.services.jsonutil import dumps
from app.services.summarize import SummarizeError

FILLED_OVERVIEW = """## 一句话总结
**调整结束后用低吸纪律做二段反弹，不看空但要等收敛。**

## 主题与核心观点
| 维度 | 内容 |
|---|---|
| 主题 | 二段反弹节奏 |
| 核心观点 | 上涨放量、调整缩量才继续做 |
| 手段 | 低吸与仓位管理 |

## 论证结构
### 一、市场节奏与操作纪律
周五冲高回落但调整收敛，属于健康形态（作者甲）。
核心结论：**只要不出现巨量下砸就不看空（作者甲）。**

## 辨立场
纪律可操作；修辞类比不能当成信号。方法边界在于等待收敛，信息只来自本场转写，不能当成荐股。"""


def _done_job(**kwargs) -> Job:
    payload = dict(
        title="卖票课",
        author="作者甲",
        source_url="https://example.com/a",
        status="done",
        stage="done",
        summary_json=dumps(
            {
                "title": "卖票",
                "overview": "整场综述不应进入模型",
                "chapters": [{"title": "卖票纪律", "bullets": ["先看分时走弱再挂单"]}],
                "key_points": [{"text": "要点也不应进入模型"}],
            }
        ),
    )
    payload.update(kwargs)
    return Job(**payload)


def test_digest_sources_keep_author_and_chapters_only():
    jobs = [
        _done_job(),
        _done_job(
            title="失败课",
            author="乙",
            source_url="https://example.com/b",
            status="failed",
            summary_json="",
        ),
    ]
    sources = digest_sources(jobs)
    assert sources == [
        {
            "author": "作者甲",
            "chapters": [{"title": "卖票纪律", "bullets": ["先看分时走弱再挂单"]}],
        }
    ]
    assert set(sources[0].keys()) == {"author", "chapters"}
    assert set(sources[0]["chapters"][0].keys()) == {"title", "bullets"}


def test_summarize_digest_returns_title_and_overview(monkeypatch):
    def fake_complete(_client, _settings, _system, _user_content):
        return {"title": "两场汇总", "overview": FILLED_OVERVIEW}

    monkeypatch.setattr("app.services.digest._complete_digest", fake_complete)
    result = summarize_digest(
        [{"author": "甲", "chapters": [{"title": "纪律", "bullets": ["先看分时"]}]}],
        AppSettingsOut(summarize_api_key="k", summarize_model="demo"),
    )
    assert result.title == "两场汇总"
    assert "一句话总结" in result.overview
    assert result.chapters == []
    assert result.key_points == []


def test_summarize_digest_requires_api_key():
    try:
        summarize_digest(
            [{"author": "甲", "chapters": [{"title": "纪律", "bullets": ["先看分时"]}]}],
            AppSettingsOut(summarize_api_key="", summarize_model="demo"),
        )
    except SummarizeError as exc:
        assert "API Key" in str(exc)
    else:
        raise AssertionError("expected SummarizeError")


def test_run_schedule_digest_creates_job(db_session, monkeypatch):
    log = ScheduleLog(trigger="manual", status="ok", summary="新建 2")
    db_session.add(log)
    db_session.commit()
    db_session.refresh(log)
    first = _done_job(schedule_log_id=log.id)
    second = _done_job(
        title="低吸课",
        author="作者乙",
        source_url="https://example.com/c",
        schedule_log_id=log.id,
        summary_json=dumps(
            {
                "title": "低吸",
                "overview": "另一场综述",
                "chapters": [{"title": "低吸条件", "bullets": ["量能配合才做"]}],
                "key_points": [],
            }
        ),
    )
    db_session.add_all([first, second])
    db_session.commit()

    captured: list[list[dict]] = []

    def fake_summarize(sources, settings):
        captured.append(sources)
        return SummaryResult(title="定时汇总", overview=FILLED_OVERVIEW)

    monkeypatch.setattr("app.services.digest.summarize_digest", fake_summarize)
    monkeypatch.setattr("app.services.digest.load_settings", lambda _db: AppSettingsOut(summarize_api_key="k"))
    monkeypatch.setattr(
        "app.services.digest.SessionLocal",
        sessionmaker(bind=db_session.get_bind(), autoflush=False, autocommit=False),
    )
    run_schedule_digest(log.id)
    db_session.expire_all()
    log = db_session.get(ScheduleLog, log.id)
    assert log.digest_job_id
    digest = db_session.get(Job, log.digest_job_id)
    assert digest is not None
    assert digest.source_type == DIGEST_SOURCE
    assert digest.status == "done"
    assert digest.source_url == f"schedule://{log.id}"
    assert "定时汇总" in digest.title
    assert captured
    assert all(set(item.keys()) == {"author", "chapters"} for item in captured[0])
    jobs = db_session.query(Job).filter(Job.source_type == DIGEST_SOURCE).all()
    assert len(jobs) == 1


def test_run_schedule_digest_skips_when_no_summaries(db_session, monkeypatch):
    log = ScheduleLog(trigger="manual", status="ok", summary="失败")
    db_session.add(log)
    db_session.commit()
    db_session.refresh(log)
    db_session.add(
        Job(
            title="失败课",
            author="甲",
            source_url="https://example.com/fail",
            status="failed",
            stage="done",
            schedule_log_id=log.id,
        )
    )
    db_session.commit()
    monkeypatch.setattr(
        "app.services.digest.SessionLocal",
        sessionmaker(bind=db_session.get_bind(), autoflush=False, autocommit=False),
    )
    run_schedule_digest(log.id)
    db_session.expire_all()
    log = db_session.get(ScheduleLog, log.id)
    assert not log.digest_job_id
    assert db_session.query(Job).filter(Job.source_type == DIGEST_SOURCE).count() == 0


def test_create_digest_from_jobs(db_session, monkeypatch):
    first = _done_job()
    second = _done_job(
        title="低吸课",
        author="作者乙",
        source_url="https://example.com/c",
        summary_json=dumps(
            {
                "title": "低吸",
                "overview": "另一场综述",
                "chapters": [{"title": "低吸条件", "bullets": ["量能配合才做"]}],
                "key_points": [],
            }
        ),
    )
    db_session.add_all([first, second])
    db_session.commit()
    digest = create_digest_from_jobs(db_session, [first.id, second.id])
    assert digest.source_type == MANUAL_DIGEST_SOURCE
    assert digest.source_url == encode_digest_source_url([first.id, second.id])
    assert "汇总" in digest.title
    assert [row.id for row in related_job_refs(db_session, digest)] == [first.id, second.id]
    monkeypatch.setattr(
        "app.services.digest.summarize_digest",
        lambda sources, settings: SummaryResult(title="手工汇总", overview=FILLED_OVERVIEW),
    )
    monkeypatch.setattr("app.services.digest.load_settings", lambda _db: AppSettingsOut(summarize_api_key="k"))
    fill_digest_job(db_session, digest)
    db_session.refresh(digest)
    assert digest.status == "done"
    assert "一句话总结" in digest.summary_json


def test_create_digest_from_jobs_requires_two_summaries(db_session):
    first = _done_job()
    pending = Job(title="未完成", source_url="https://example.com/p", status="pending", stage="queued")
    db_session.add_all([first, pending])
    db_session.commit()
    try:
        create_digest_from_jobs(db_session, [first.id, pending.id])
    except ValueError as exc:
        assert "至少需要 2 个" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_digest_jobs_endpoint(client, db_session, monkeypatch):
    first = _done_job()
    second = _done_job(title="低吸课", author="作者乙", source_url="https://example.com/c")
    db_session.add_all([first, second])
    db_session.commit()
    queued: list[str] = []
    monkeypatch.setattr("app.routers.jobs._enqueue", queued.append)
    created = client.post("/api/jobs/digest", json={"ids": [first.id, second.id]})
    assert created.status_code == 200
    payload = created.json()
    assert payload["source_type"] == MANUAL_DIGEST_SOURCE
    assert payload["related_jobs"][0]["id"] == first.id
    assert payload["related_jobs"][1]["id"] == second.id
    assert queued == [payload["id"]]
    too_few = client.post("/api/jobs/digest", json={"ids": [first.id]})
    assert too_few.status_code == 422
    missing = client.post("/api/jobs/digest", json={"ids": [first.id, "missing-id"]})
    assert missing.status_code == 400
    assert missing.json()["detail"] == "任务不存在"
