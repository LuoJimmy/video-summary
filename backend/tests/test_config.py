from pathlib import Path

from sqlalchemy import create_engine, text

from app.config import Settings
from app.database import migrate_job_columns
from app.services.pipeline import StageTimer


def test_summarize_concurrency_clamped(tmp_path):
    settings = Settings(data_dir=tmp_path, summarize_concurrency=3)
    assert settings.summarize_concurrency == 3


def test_resolve_job_audio_path_remaps_stale_downloads(tmp_path):
    settings = Settings(data_dir=tmp_path, download_dir="")
    job_id = "563c320137c14a47afef811c5c68925b"
    local = settings.uploads_path() / job_id / "audio.wav"
    local.parent.mkdir(parents=True, exist_ok=True)
    local.write_bytes(b"RIFF")
    resolved = settings.resolve_job_audio_path(job_id, f"/downloads/{job_id}/audio.wav")
    assert resolved == local
    assert resolved.is_file()


def test_resolve_job_audio_path_keeps_file_under_uploads(tmp_path):
    settings = Settings(data_dir=tmp_path, download_dir="")
    job_id = "abc123"
    local = settings.uploads_path() / job_id / "audio.wav"
    local.parent.mkdir(parents=True, exist_ok=True)
    local.write_bytes(b"RIFF")
    assert settings.resolve_job_audio_path(job_id, str(local)) == local


def test_uploads_path_uses_download_dir(tmp_path):
    download = tmp_path / "media"
    settings = Settings(data_dir=tmp_path / "data", download_dir=str(download))
    assert settings.uploads_path() == download
    assert download.is_dir()
    assert settings.models_path() == tmp_path / "data" / "models"


def test_resolved_static_dir_missing_is_none(tmp_path):
    settings = Settings(data_dir=tmp_path, static_dir=str(tmp_path / "no-such"))
    assert settings.resolved_static_dir() is None
    (tmp_path / "web").mkdir()
    settings = Settings(data_dir=tmp_path, static_dir=str(tmp_path / "web"))
    assert settings.resolved_static_dir() == tmp_path / "web"


def test_stage_timer_records_total():
    timer = StageTimer()
    timer.start("transcribing")
    timer.stop("transcribing")
    payload = timer.payload()
    assert payload["transcribing"] >= 0
    assert payload["total"] >= payload["transcribing"]


def test_migrate_job_columns_adds_timing(tmp_path, monkeypatch):
    from app import database

    engine = create_engine(f"sqlite:///{tmp_path}/old.db")
    monkeypatch.setattr(database, "engine", engine)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE jobs (id VARCHAR(32) PRIMARY KEY, title VARCHAR(255))"))
    database.migrate_job_columns()
    with engine.connect() as conn:
        names = {row[1] for row in conn.execute(text("PRAGMA table_info(jobs)")).fetchall()}
    assert "timing_json" in names
    assert "started_at" in names
    assert "source_created_at" in names
    assert "domain_id" in names
