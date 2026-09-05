from datetime import datetime
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import AppSetting, Job
from app.schemas import SummaryResult, TranscriptSegment
from app.services.jsonutil import loads
from app.services.media import MediaExtractor
from app.services.pipeline import Pipeline
from app.services.summarize import Summarizer
from app.services.transcribe import Transcriber


def test_health(client):
    assert client.get("/api/health").json()["ok"] is True


def test_seeded_sites_and_profiles(client):
    profiles = client.get("/api/profiles").json()
    sites = client.get("/api/sites").json()
    assert len(profiles) == 3
    assert {item["adapter"] for item in sites} == {"xiaoe", "yueniu", "bilibili", "generic"}


def test_update_profile_cookie(client):
    profile_id = client.get("/api/profiles").json()[0]["id"]
    payload = {
        "name": "小鹅通登录档案",
        "cookie": "ko_token=abc",
        "extra_headers": {"Referer": "https://etrsz.xetslk.com/"},
        "notes": "已登录",
    }
    updated = client.put(f"/api/profiles/{profile_id}", json=payload).json()
    assert updated["cookie"] == "ko_token=abc"
    assert updated["extra_headers"]["Referer"].startswith("https://etrsz")


def test_settings_roundtrip(client):
    saved = client.put(
        "/api/settings",
        json={
            "transcribe_base_url": "http://127.0.0.1:9000/v1",
            "transcribe_api_key": "t-key",
            "transcribe_model": "whisper-1",
            "summarize_base_url": "http://127.0.0.1:8000/v1",
            "summarize_api_key": "s-key",
            "summarize_model": "demo",
        },
    ).json()
    assert saved["transcribe_api_key"] == "t-key"
    loaded = client.get("/api/settings").json()
    assert loaded["summarize_model"] == "demo"
    assert loaded["summarize_concurrency"] == 3
    assert loaded["ai_proofread"] is True
    assert loaded["show_transcript"] is True
    assert loaded["transcribe_fast"] is False
    assert loaded["cpu_count"] >= 1
    assert 1 <= loaded["transcribe_threads"] <= loaded["cpu_count"]
    assert loaded["domain_pack"]["id"] == "a-share"
    assert loaded["domain_pack"]["name"] == "A股盘面课"
    assert any(item["id"] == "generic" for item in loaded["domain_presets"])

    flags = client.put(
        "/api/settings",
        json={
            "transcribe_base_url": "http://127.0.0.1:9000/v1",
            "transcribe_api_key": "t-key",
            "transcribe_model": "whisper-1",
            "summarize_base_url": "http://127.0.0.1:8000/v1",
            "summarize_api_key": "s-key",
            "summarize_model": "demo",
            "ai_proofread": False,
            "show_transcript": False,
        },
    ).json()
    assert flags["ai_proofread"] is False
    assert flags["show_transcript"] is False
    again = client.get("/api/settings").json()
    assert again["ai_proofread"] is False
    assert again["show_transcript"] is False


def test_domain_pack_roundtrip(client):
    loaded = client.get("/api/settings").json()
    generic = next(item for item in loaded["domain_presets"] if item["id"] == "generic")
    saved = client.put(
        "/api/settings",
        json={
            "summarize_model": "demo",
            "domain_pack": generic,
        },
    ).json()
    assert saved["domain_pack"]["id"] == "generic"
    assert saved["domain_pack"]["highlight_stock_codes"] is False
    again = client.get("/api/settings").json()
    assert again["domain_pack"]["name"] == "通用课程"
    only_pack = client.put("/api/settings", json={"domain_pack": generic}).json()
    assert only_pack["domain_pack"]["id"] == "generic"
    assert only_pack["summarize_model"] == "demo"
    lexicon = client.get("/api/lexicon").json()
    assert lexicon["preset"] == "generic"
    assert "打板" not in lexicon["terms"]
    ashare = client.get("/api/lexicon", params={"preset": "a-share"}).json()
    assert ashare["preset"] == "a-share"
    assert "打板" in ashare["terms"]


def test_domain_preset_crud_and_job_domain(client):
    created = client.post(
        "/api/settings/domain-presets",
        json={"source_id": "generic", "name": "理财课"},
    ).json()
    pack = created["domain_pack"]
    assert pack["name"] == "理财课"
    assert pack["id"] != "generic"
    assert any(item["id"] == pack["id"] for item in created["domain_presets"])
    tagged = client.post(
        "/api/jobs",
        json={"source_url": "https://cdn.example.com/a.mp4", "domain_id": pack["id"]},
    ).json()
    assert tagged["domain_id"] == pack["id"]
    defaulted = client.post(
        "/api/jobs",
        json={"source_url": "https://cdn.example.com/b.mp4"},
    ).json()
    assert defaulted["domain_id"] == "a-share"
    blocked = client.delete("/api/settings/domain-presets/a-share")
    assert blocked.status_code == 400
    gone = client.delete(f"/api/settings/domain-presets/{pack['id']}").json()
    assert gone["domain_pack"]["id"] == "a-share"
    assert all(item["id"] != pack["id"] for item in gone["domain_presets"])


def test_lexicon_roundtrip_and_reset(client):
    loaded = client.get("/api/lexicon").json()
    assert loaded["customized"] is False
    assert loaded["preset"] == "a-share"
    assert "打板" in loaded["terms"]
    assert "弱转强" in loaded["terms"]
    assert any(item["wrong"] == "打版" and item["right"] == "打板" for item in loaded["fixes"])

    saved = client.put(
        "/api/lexicon",
        json={
            "terms": ["自定义词", "龙头"],
            "fixes": [{"wrong": "笼头", "right": "龙头"}, {"wrong": "打版", "right": "打板"}],
        },
    ).json()
    assert saved["customized"] is True
    assert saved["terms"] == ["自定义词", "龙头"]
    assert saved["fixes"] == [{"wrong": "笼头", "right": "龙头"}, {"wrong": "打版", "right": "打板"}]
    again = client.get("/api/lexicon").json()
    assert again["terms"] == ["自定义词", "龙头"]

    reset = client.post("/api/lexicon/reset").json()
    assert reset["customized"] is False
    assert "打板" in reset["terms"]
    assert "自定义词" not in reset["terms"]


def test_create_job_and_list(client):
    created = client.post(
        "/api/jobs",
        json={"source_url": "https://cdn.example.com/a.mp4", "title": "直链"},
    ).json()
    assert created["status"] == "pending"
    assert created["domain_id"] == "a-share"
    assert created["started_at"]
    assert created["source_created_at"] is None
    listed = client.get("/api/jobs").json()
    assert listed["total"] == 1
    assert listed["page"] == 1
    assert listed["items"][0]["id"] == created["id"]
    assert listed["items"][0]["transcript"] == []
    assert listed["items"][0]["summary"] is None


def test_list_jobs_paginated(client):
    for index in range(3):
        client.post("/api/jobs", json={"source_url": f"https://cdn.example.com/{index}.mp4", "title": f"t{index}"})
    all_items = client.get("/api/jobs", params={"page": 1, "page_size": 100}).json()["items"]
    assert len(all_items) == 3
    page1 = client.get("/api/jobs", params={"page": 1, "page_size": 2}).json()
    assert page1["total"] == 3
    assert page1["page"] == 1
    assert page1["page_size"] == 2
    assert [item["id"] for item in page1["items"]] == [item["id"] for item in all_items[:2]]
    page2 = client.get("/api/jobs", params={"page": 2, "page_size": 2}).json()
    assert [item["id"] for item in page2["items"]] == [item["id"] for item in all_items[2:]]
    empty = client.get("/api/jobs", params={"page": 9, "page_size": 2}).json()
    assert empty["items"] == []
    assert empty["total"] == 3
    invalid = client.get("/api/jobs", params={"page": 0})
    assert invalid.status_code == 422


def test_list_jobs_filtered(client, db_session):
    early = datetime(2026, 8, 13, 4, 0, 0)
    late = datetime(2026, 9, 1, 8, 0, 0)
    rows = [
        Job(title="卖票方法", source_url="https://cdn.example.com/a.mp4", status="done", stage="done", source_created_at=early, created_at=late),
        Job(title="低吸条件", source_url="https://cdn.example.com/b.mp4", status="failed", stage="failed", source_created_at=late, created_at=late),
        Job(title="处理中的卖票", source_url="https://cdn.example.com/c.mp4", status="running", stage="transcribing", created_at=early),
        Job(title="已取消", source_url="https://cdn.example.com/d.mp4", status="cancelled", stage="cancelled", source_created_at=early, created_at=late),
    ]
    db_session.add_all(rows)
    db_session.commit()

    by_title = client.get("/api/jobs", params={"title": "卖票"}).json()
    assert by_title["total"] == 2
    assert {item["title"] for item in by_title["items"]} == {"卖票方法", "处理中的卖票"}

    listed = client.get("/api/jobs", params={"page_size": 100}).json()
    assert listed["items"][0]["title"] == "低吸条件"
    assert {item["title"] for item in listed["items"][1:]} == {"卖票方法", "已取消", "处理中的卖票"}
    by_created = client.get("/api/jobs", params={"sort": "created", "page_size": 100}).json()
    assert by_created["items"][-1]["title"] == "处理中的卖票"
    assert {item["title"] for item in by_created["items"][:3]} == {"已取消", "低吸条件", "卖票方法"}
    by_created_asc = client.get(
        "/api/jobs", params={"sort": "created", "order": "asc", "page_size": 100}
    ).json()
    assert by_created_asc["items"][0]["title"] == "处理中的卖票"
    by_title = client.get("/api/jobs", params={"sort": "title", "order": "asc", "page_size": 100}).json()
    assert [item["title"] for item in by_title["items"]] == ["低吸条件", "卖票方法", "处理中的卖票", "已取消"]
    by_title_desc = client.get("/api/jobs", params={"sort": "title", "page_size": 100}).json()
    assert [item["title"] for item in by_title_desc["items"]] == ["已取消", "处理中的卖票", "卖票方法", "低吸条件"]
    by_source_asc = client.get("/api/jobs", params={"order": "asc", "page_size": 100}).json()
    assert by_source_asc["items"][-1]["title"] == "低吸条件"
    assert {item["title"] for item in by_source_asc["items"][:3]} == {"卖票方法", "已取消", "处理中的卖票"}
    invalid_sort = client.get("/api/jobs", params={"sort": "nope"})
    assert invalid_sort.status_code == 422
    invalid_order = client.get("/api/jobs", params={"order": "nope"})
    assert invalid_order.status_code == 422

    by_status = client.get("/api/jobs", params={"status": "failed"}).json()
    assert [item["title"] for item in by_status["items"]] == ["低吸条件"]

    active = client.get("/api/jobs", params={"status": "active"}).json()
    assert [item["title"] for item in active["items"]] == ["处理中的卖票"]

    by_date = client.get(
        "/api/jobs",
        params={"date_from": "2026-08-13T00:00:00Z", "date_to": "2026-08-14T00:00:00Z"},
    ).json()
    assert {item["title"] for item in by_date["items"]} == {"卖票方法", "处理中的卖票", "已取消"}

    combined = client.get(
        "/api/jobs",
        params={"title": "卖票", "status": "done", "date_from": "2026-08-13T00:00:00Z", "date_to": "2026-08-14T00:00:00Z"},
    ).json()
    assert [item["title"] for item in combined["items"]] == ["卖票方法"]

    paged = client.get("/api/jobs", params={"title": "卖票", "page": 1, "page_size": 1}).json()
    assert paged["total"] == 2
    assert len(paged["items"]) == 1

    invalid = client.get("/api/jobs", params={"status": "nope"})
    assert invalid.status_code == 422


def test_update_job_title(client):
    created = client.post("/api/jobs", json={"source_url": "https://cdn.example.com/a.mp4", "title": "旧标题"}).json()
    updated = client.patch(f"/api/jobs/{created['id']}", json={"title": "  新标题  "}).json()
    assert updated["title"] == "新标题"
    loaded = client.get(f"/api/jobs/{created['id']}").json()
    assert loaded["title"] == "新标题"
    listed = client.get("/api/jobs").json()
    assert listed["items"][0]["title"] == "新标题"
    missing = client.patch("/api/jobs/does-not-exist", json={"title": "x"})
    assert missing.status_code == 404
    too_long = client.patch(f"/api/jobs/{created['id']}", json={"title": "x" * 256})
    assert too_long.status_code == 422


def test_knowledge_indexes_transcripts(client, db_session):
    from app.services.jsonutil import dumps

    empty = client.get("/api/knowledge").json()
    assert empty["job_count"] == 0

    job = Job(
        title="行情课",
        status="done",
        transcript_json=dumps(
            [
                {"id": 0, "start": 0, "end": 8, "text": "今天重点看贵州茅台"},
                {"id": 1, "start": 8, "end": 16, "text": "成交量放大可以低吸"},
            ]
        ),
        summary_json=dumps({"title": "复盘", "overview": "讨论成交量与低吸", "chapters": [], "key_points": []}),
    )
    db_session.add(job)
    db_session.commit()

    listed = client.get("/api/knowledge").json()
    assert listed["job_count"] == 1
    assert listed["documents"][0]["title"] == "行情课"
    assert listed["documents"][0]["segment_count"] == 2

    found = client.get("/api/knowledge", params={"q": "茅台"}).json()
    assert found["hit_count"] >= 1
    assert any("茅台" in item["text"] for item in found["hits"])

    miss = client.get("/api/knowledge", params={"q": "xyznotfound"}).json()
    assert miss["hit_count"] == 0

    denied = client.post("/api/knowledge/chat", json={"messages": [{"role": "user", "content": "低吸条件"}]})
    assert denied.status_code == 400

    asked = client.get("/api/knowledge", params={"q": "低吸条件是什么"}).json()
    assert asked["hit_count"] >= 1


def test_knowledge_paginates_documents(client, db_session):
    from datetime import timedelta

    from app.services.jsonutil import dumps

    now = datetime(2026, 9, 5, 2, 0, 0)
    for index in range(3):
        db_session.add(
            Job(
                title=f"课{index + 1}",
                status="done",
                transcript_json=dumps([{"id": 0, "start": 0, "end": 8, "text": f"内容{index + 1}"}]),
                updated_at=now - timedelta(minutes=index),
            )
        )
    db_session.add(
        Job(
            title="通用课",
            status="done",
            domain_id="generic",
            transcript_json=dumps([{"id": 0, "start": 0, "end": 8, "text": "通用内容"}]),
        )
    )
    db_session.commit()

    page1 = client.get("/api/knowledge", params={"page": 1, "page_size": 2}).json()
    assert page1["job_count"] == 3
    assert page1["page"] == 1
    assert page1["page_size"] == 2
    assert [item["title"] for item in page1["documents"]] == ["课1", "课2"]

    page2 = client.get("/api/knowledge", params={"page": 2, "page_size": 2}).json()
    assert page2["job_count"] == 3
    assert [item["title"] for item in page2["documents"]] == ["课3"]

    generic = client.get("/api/knowledge", params={"domain_id": "generic", "page_size": 10}).json()
    assert generic["job_count"] == 1
    assert generic["documents"][0]["title"] == "通用课"


def test_delete_job(client, db_session, tmp_path, monkeypatch):
    from app.config import settings as app_settings

    monkeypatch.setattr(app_settings, "download_dir", str(tmp_path / "uploads"))
    created = client.post("/api/jobs", json={"source_url": "https://cdn.example.com/a.mp4", "title": "待删除"}).json()
    folder = tmp_path / "uploads" / created["id"]
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "audio.wav").write_bytes(b"wav")

    missing = client.delete("/api/jobs/does-not-exist")
    assert missing.status_code == 404

    deleted = client.delete(f"/api/jobs/{created['id']}").json()
    assert deleted["ok"] is True
    listed = client.get("/api/jobs").json()
    assert all(item["id"] != created["id"] for item in listed["items"])
    assert db_session.get(Job, created["id"]) is None
    assert not folder.exists()


def test_cancel_pending_job(client, db_session):
    created = client.post("/api/jobs", json={"source_url": "https://cdn.example.com/a.mp4", "title": "待取消"}).json()
    cancelled = client.post(f"/api/jobs/{created['id']}/cancel").json()
    assert cancelled["status"] == "cancelled"
    assert cancelled["error"] == "已取消"
    again = client.post(f"/api/jobs/{created['id']}/cancel").json()
    assert again["status"] == "cancelled"

    finished = client.post("/api/jobs", json={"source_url": "https://cdn.example.com/b.mp4", "title": "完成态"}).json()
    row = db_session.get(Job, finished["id"])
    row.status = "done"
    row.stage = "done"
    db_session.commit()
    denied = client.post(f"/api/jobs/{finished['id']}/cancel")
    assert denied.status_code == 400


class FakeExtractor(MediaExtractor):
    def extract_audio(self, source, output_wav, extra_headers=None, max_seconds=None):
        Path(output_wav).parent.mkdir(parents=True, exist_ok=True)
        Path(output_wav).write_bytes(b"RIFF")
        return Path(output_wav)


class FakeTranscriber(Transcriber):
    def transcribe(self, audio_path, settings):
        return [
            TranscriptSegment(id=0, start=0, end=8, text="今天复盘市场"),
            TranscriptSegment(id=1, start=8, end=20, text="重点看成交量"),
        ]


class FakeSummarizer(Summarizer):
    def summarize(self, segments, settings):
        return SummaryResult(
            title="复盘",
            overview="讨论成交量",
            chapters=[],
            key_points=[],
        )


def test_pipeline_with_local_file(tmp_path, monkeypatch):
    from app import database
    from app.config import settings as app_settings

    db_path = tmp_path / "pipe.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    monkeypatch.setattr(database, "engine", engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(database, "SessionLocal", session_factory)
    monkeypatch.setattr("app.services.pipeline.SessionLocal", session_factory)
    monkeypatch.setattr(app_settings, "data_dir", tmp_path)
    database.Base.metadata.create_all(engine)

    source = tmp_path / "clip.mp4"
    source.write_bytes(b"video")
    db = session_factory()
    job = Job(title="本地", source_url=str(source), source_path=str(source), status="pending")
    db.add(job)
    db.commit()
    job_id = job.id
    db.close()

    pipeline = Pipeline(extractor=FakeExtractor(), transcriber=FakeTranscriber(), summarizer=FakeSummarizer())
    pipeline.run_job(job_id)

    db = session_factory()
    stored = db.get(Job, job_id)
    assert stored.status == "done"
    assert stored.source_created_at is not None
    assert stored.title == "本地"
    assert "今天复盘市场" in stored.transcript_json
    assert stored.progress == 100
    timing = loads(stored.timing_json, {})
    assert "total" in timing
    assert "transcribing" in timing
    assert "summarizing" in timing
    db.close()


def test_pipeline_skips_ai_proofread_when_disabled(tmp_path, monkeypatch):
    from app import database
    from app.config import settings as app_settings

    db_path = tmp_path / "skip-proof.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(database, "engine", engine)
    monkeypatch.setattr(database, "SessionLocal", session_factory)
    monkeypatch.setattr("app.services.pipeline.SessionLocal", session_factory)
    monkeypatch.setattr(app_settings, "data_dir", tmp_path)
    database.Base.metadata.create_all(engine)

    source = tmp_path / "clip.mp4"
    source.write_bytes(b"video")
    db = session_factory()
    job = Job(title="跳过校对", source_url=str(source), source_path=str(source), status="pending")
    db.add(job)
    db.add(AppSetting(key="ai_proofread", value="0"))
    db.commit()
    job_id = job.id
    db.close()

    called = {"n": 0}

    def mark_proofread(segments, settings, use_llm=False):
        called["n"] += 1
        return segments

    monkeypatch.setattr("app.services.pipeline.proofread_transcript", mark_proofread)
    Pipeline(extractor=FakeExtractor(), transcriber=FakeTranscriber(), summarizer=FakeSummarizer()).run_job(job_id)
    db = session_factory()
    stored = db.get(Job, job_id)
    assert stored.status == "done"
    assert called["n"] == 0
    timing = loads(stored.timing_json, {})
    assert "proofreading" not in timing
    assert "summarizing" in timing
    db.close()


def test_pipeline_remaps_stale_downloads_audio(tmp_path, monkeypatch):
    from app import database
    from app.config import settings as app_settings

    db_path = tmp_path / "remap.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(database, "engine", engine)
    monkeypatch.setattr(database, "SessionLocal", session_factory)
    monkeypatch.setattr("app.services.pipeline.SessionLocal", session_factory)
    monkeypatch.setattr(app_settings, "data_dir", tmp_path)
    monkeypatch.setattr(app_settings, "download_dir", "")
    database.Base.metadata.create_all(engine)

    job_id = "563c320137c14a47afef811c5c68925b"
    local = tmp_path / "uploads" / job_id / "audio.wav"
    local.parent.mkdir(parents=True, exist_ok=True)
    local.write_bytes(b"RIFF" + b"\x00" * 2048)
    db = session_factory()
    job = Job(
        id=job_id,
        title="旧路径",
        source_url="https://cdn.example.com/a.mp4",
        audio_path=f"/downloads/{job_id}/audio.wav",
        status="pending",
    )
    db.add(job)
    db.commit()
    db.close()

    class TrackingExtractor(FakeExtractor):
        def extract_audio(self, source, output_wav, extra_headers=None, max_seconds=None):
            assert Path(output_wav).parts[:1] != ("/",) or "downloads" not in Path(output_wav).parts
            raise AssertionError("本机已有抽音，不应再写 /downloads")

    Pipeline(extractor=TrackingExtractor(), transcriber=FakeTranscriber(), summarizer=FakeSummarizer()).run_job(job_id)
    db = session_factory()
    stored = db.get(Job, job_id)
    assert stored.status == "done"
    assert stored.audio_path == str(local)
    db.close()


def test_pipeline_stops_when_cancelled(tmp_path, monkeypatch):
    from app import database
    from app.config import settings as app_settings
    from app.services.cancel import current_job_id, request_cancel, raise_if_cancelled

    db_path = tmp_path / "cancel.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(database, "engine", engine)
    monkeypatch.setattr(database, "SessionLocal", session_factory)
    monkeypatch.setattr("app.services.pipeline.SessionLocal", session_factory)
    monkeypatch.setattr(app_settings, "data_dir", tmp_path)
    database.Base.metadata.create_all(engine)

    source = tmp_path / "clip.mp4"
    source.write_bytes(b"video")
    db = session_factory()
    job = Job(title="取消中", source_url=str(source), source_path=str(source), status="pending")
    db.add(job)
    db.commit()
    job_id = job.id
    db.close()

    class CancellingTranscriber(Transcriber):
        def transcribe(self, audio_path, settings):
            request_cancel(current_job_id())
            raise_if_cancelled()
            return [TranscriptSegment(id=0, start=0, end=1, text="不应出现")]

    Pipeline(extractor=FakeExtractor(), transcriber=CancellingTranscriber(), summarizer=FakeSummarizer()).run_job(job_id)
    db = session_factory()
    stored = db.get(Job, job_id)
    assert stored.status == "cancelled"
    assert stored.transcript_json == ""
    db.close()


def test_retranscribe_uses_existing_audio(tmp_path, monkeypatch):
    from app import database
    from app.config import settings as app_settings
    from app.services.jsonutil import dumps

    db_path = tmp_path / "retranscribe.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr("app.services.pipeline.SessionLocal", session_factory)
    monkeypatch.setattr(app_settings, "data_dir", tmp_path)
    monkeypatch.setattr(app_settings, "download_dir", "")
    database.Base.metadata.create_all(engine)

    job_id = "aa" * 16
    local = tmp_path / "uploads" / job_id / "audio.wav"
    local.parent.mkdir(parents=True, exist_ok=True)
    local.write_bytes(b"RIFF" + b"\x00" * 2048)
    db = session_factory()
    job = Job(
        id=job_id,
        title="重转写",
        source_url="https://cdn.example.com/a.mp4",
        audio_path=str(local),
        status="done",
        transcript_json=dumps([{"id": 0, "start": 0, "end": 1, "text": "旧转写"}]),
    )
    db.add(job)
    db.commit()
    db.close()

    class TrackingExtractor(FakeExtractor):
        def extract_audio(self, source, output_wav, extra_headers=None, max_seconds=None):
            raise AssertionError("已有音频时重转写不应再抽音")

    Pipeline(extractor=TrackingExtractor(), transcriber=FakeTranscriber(), summarizer=FakeSummarizer()).retranscribe_job(job_id)
    db = session_factory()
    stored = db.get(Job, job_id)
    assert stored.status == "done"
    assert "今天复盘市场" in stored.transcript_json
    timing = loads(stored.timing_json, {})
    assert "transcribing" in timing
    assert "total" in timing
    db.close()


def test_retranscribe_can_stop_after_transcribe(tmp_path, monkeypatch):
    from app import database
    from app.config import settings as app_settings
    from app.services.jsonutil import dumps

    db_path = tmp_path / "retranscribe-only.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr("app.services.pipeline.SessionLocal", session_factory)
    monkeypatch.setattr(app_settings, "data_dir", tmp_path)
    monkeypatch.setattr(app_settings, "download_dir", "")
    database.Base.metadata.create_all(engine)

    job_id = "bb" * 16
    local = tmp_path / "uploads" / job_id / "audio.wav"
    local.parent.mkdir(parents=True, exist_ok=True)
    local.write_bytes(b"RIFF" + b"\x00" * 2048)
    db = session_factory()
    job = Job(
        id=job_id,
        title="只转写",
        source_url="https://cdn.example.com/a.mp4",
        audio_path=str(local),
        status="done",
        transcript_json=dumps([{"id": 0, "start": 0, "end": 1, "text": "旧转写"}]),
        summary_json='{"title":"旧总结"}',
    )
    db.add(job)
    db.commit()
    db.close()

    def boom(*args, **kwargs):
        raise AssertionError("只转写时不应进入校对")

    class TrackingSummarizer(FakeSummarizer):
        def summarize(self, segments, settings):
            raise AssertionError("只转写时不应进入总结")

    monkeypatch.setattr("app.services.pipeline.proofread_transcript", boom)
    Pipeline(extractor=FakeExtractor(), transcriber=FakeTranscriber(), summarizer=TrackingSummarizer()).retranscribe_job(
        job_id, continue_after=False
    )
    db = session_factory()
    stored = db.get(Job, job_id)
    assert stored.status == "done"
    assert "今天复盘市场" in stored.transcript_json
    assert stored.summary_json == '{"title":"旧总结"}'
    timing = loads(stored.timing_json, {})
    assert "transcribing" in timing
    assert "proofreading" not in timing
    assert "summarizing" not in timing
    db.close()


def test_resummarize_existing_transcript(tmp_path, monkeypatch):
    from app import database
    from app.services.jsonutil import dumps

    db_path = tmp_path / "resume.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr("app.services.pipeline.SessionLocal", session_factory)
    database.Base.metadata.create_all(engine)
    db = session_factory()
    job = Job(
        title="已有转写",
        source_url="https://example.com/a.mp4",
        status="done",
        transcript_json=dumps([{"id": 0, "start": 0, "end": 3, "text": "开场"}]),
    )
    db.add(job)
    db.commit()
    job_id = job.id
    db.close()
    Pipeline(summarizer=FakeSummarizer()).resummarize_job(job_id)
    db = session_factory()
    stored = db.get(Job, job_id)
    assert stored.status == "done"
    assert "复盘" in stored.summary_json
    db.close()


def test_proofread_existing_transcript_fixes_glossary(tmp_path, monkeypatch):
    from app.services.jsonutil import dumps, loads

    db_path = tmp_path / "proofread.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr("app.services.pipeline.SessionLocal", session_factory)
    from app import database

    database.Base.metadata.create_all(engine)
    db = session_factory()
    job = Job(
        title="盘面课",
        source_url="https://example.com/a.mp4",
        status="done",
        transcript_json=dumps(
            [
                {
                    "id": 0,
                    "start": 0,
                    "end": 5,
                    "text": "只要覆反会不扩大，每一次挑准都可以参与",
                }
            ]
        ),
    )
    db.add(job)
    db.commit()
    job_id = job.id
    db.close()
    Pipeline(summarizer=FakeSummarizer()).proofread_job(job_id)
    db = session_factory()
    stored = db.get(Job, job_id)
    assert stored.status == "done"
    texts = [item["text"] for item in loads(stored.transcript_json, [])]
    assert texts == ["只要负反馈不会太大，每一次调整都可以参与"]
    assert "复盘" in stored.summary_json
    db.close()


def test_proofread_api_starts_job(client, db_session):
    from app.services.jsonutil import dumps

    job = Job(
        title="校对",
        source_url="https://example.com/a.mp4",
        status="done",
        transcript_json=dumps([{"id": 0, "start": 0, "end": 1, "text": "开场"}]),
    )
    db_session.add(job)
    db_session.commit()
    response = client.post(f"/api/jobs/{job.id}/proofread")
    assert response.status_code == 200
    assert response.json()["stage"] == "proofreading"


def test_retranscribe_api_starts_job(client, db_session):
    from app.services.jsonutil import dumps

    job = Job(
        title="重转写",
        source_url="https://example.com/a.mp4",
        status="done",
        transcript_json=dumps([{"id": 0, "start": 0, "end": 1, "text": "开场"}]),
    )
    db_session.add(job)
    db_session.commit()
    response = client.post(f"/api/jobs/{job.id}/retranscribe")
    assert response.status_code == 200
    assert response.json()["stage"] == "transcribing"
    assert response.json()["progress"] == 50
    assert response.json()["started_at"]
    only = client.post(f"/api/jobs/{job.id}/retranscribe", params={"continue_after": False})
    assert only.status_code == 200
    assert only.json()["stage"] == "transcribing"
