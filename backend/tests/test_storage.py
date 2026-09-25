import os

from app.config import settings as app_settings
from app.models import AppSetting, Job
from app.services.audio_store import ARCHIVE_NAME, WAV_NAME
from app.services.media import MediaError
from app.services.storage import enforce_play_quota


def _write(path, size: int = 16) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)


def _isolate(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(app_settings, "data_dir", tmp_path)
    monkeypatch.setattr(app_settings, "download_dir", "")


def test_storage_usage_counts_audio_play_source_and_orphans(client, db_session, tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path)
    job = Job(title="有归档", status="done")
    db_session.add(job)
    db_session.commit()
    workdir = app_settings.job_workdir(job.id)
    _write(workdir / ARCHIVE_NAME, 10)
    _write(workdir / "play.mp4", 20)
    _write(workdir / "source.pdf", 30)
    _write(app_settings.uploads_path() / ("0" * 32) / WAV_NAME, 40)

    payload = client.get("/api/settings/storage").json()
    assert payload["archive_files"] == 1
    assert payload["archive_bytes"] == 10
    assert payload["play_files"] == 1
    assert payload["play_bytes"] == 20
    assert payload["source_bytes"] == 30
    assert payload["wav_files"] == 1
    assert payload["wav_bytes"] == 40
    assert payload["orphan_dirs"] == 1
    assert payload["total_bytes"] == 100


def test_cleanup_audio_archives_removes_only_opus(client, db_session, tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path)
    job = Job(title="待清理", status="done")
    db_session.add(job)
    db_session.commit()
    workdir = app_settings.job_workdir(job.id)
    archive = workdir / ARCHIVE_NAME
    wav = workdir / WAV_NAME
    _write(archive, 64)
    _write(wav, 128)

    payload = client.post("/api/settings/storage/cleanup-audio").json()
    assert payload["removed_files"] == 1
    assert payload["freed_bytes"] == 64
    assert payload["usage"]["archive_files"] == 0
    assert payload["usage"]["wav_bytes"] == 128
    assert not archive.exists()
    assert wav.exists()


def test_cleanup_audio_archives_without_archive_is_noop(client, db_session, tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path)
    payload = client.post("/api/settings/storage/cleanup-audio").json()
    assert payload["removed_files"] == 0
    assert payload["freed_bytes"] == 0


def test_archive_wav_endpoint_converts_existing_audio(client, db_session, tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path)
    job = Job(title="老任务", status="done")
    db_session.add(job)
    db_session.commit()
    workdir = app_settings.job_workdir(job.id)
    wav = workdir / WAV_NAME
    _write(wav, 400)

    def fake_run(cmd, output, **kwargs):
        output.write_bytes(b"OggS" * 10)
        return output

    monkeypatch.setattr("app.services.audio_store.resolve_ffmpeg", lambda: "ffmpeg")
    monkeypatch.setattr("app.services.audio_store.run_ffmpeg", fake_run)
    payload = client.post("/api/settings/storage/archive-wav").json()
    assert payload["archived_files"] == 1
    assert payload["saved_bytes"] == 360
    assert payload["failed_files"] == 0
    assert payload["usage"]["archive_files"] == 1
    assert payload["usage"]["wav_files"] == 0
    assert not wav.exists()
    assert (workdir / ARCHIVE_NAME).exists()


def test_archive_wav_endpoint_keeps_wav_on_failure(client, db_session, tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path)
    job = Job(title="压缩失败", status="done")
    db_session.add(job)
    db_session.commit()
    wav = app_settings.job_workdir(job.id) / WAV_NAME
    _write(wav, 200)

    def boom(cmd, output, **kwargs):
        raise MediaError("ffmpeg 音频归档失败")

    monkeypatch.setattr("app.services.audio_store.resolve_ffmpeg", lambda: "ffmpeg")
    monkeypatch.setattr("app.services.audio_store.run_ffmpeg", boom)
    payload = client.post("/api/settings/storage/archive-wav").json()
    assert payload["archived_files"] == 0
    assert payload["failed_files"] == 1
    assert payload["saved_bytes"] == 0
    assert payload["usage"]["wav_files"] == 1
    assert wav.exists()


def test_play_quota_unset_keeps_play_cache(client, db_session, tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path)
    job = Job(title="默认不限制", status="done")
    db_session.add(job)
    db_session.commit()
    play = app_settings.job_workdir(job.id) / "play.mp4"
    _write(play, 3 * 1024 * 1024)

    payload = client.get("/api/settings/storage").json()
    assert payload["play_quota_bytes"] == 0
    assert payload["play_bytes"] == 3 * 1024 * 1024
    assert play.exists()


def test_play_quota_endpoint_removes_oldest_play_cache(client, db_session, tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path)
    jobs = [Job(title=f"缓存 {index}", status="done") for index in range(3)]
    db_session.add_all(jobs)
    db_session.commit()
    files = []
    for index, job in enumerate(jobs):
        path = app_settings.job_workdir(job.id) / "play.mp4"
        _write(path, 1024 * 1024)
        stamp = 1_000_000 + index
        os.utime(path, (stamp, stamp))
        files.append(path)

    response = client.put("/api/settings", json={"play_quota_mb": 2})
    assert response.status_code == 200
    assert response.json()["play_quota_mb"] == 2
    assert not files[0].exists()
    assert files[1].exists()
    assert files[2].exists()
    payload = client.get("/api/settings/storage").json()
    assert payload["play_files"] == 2
    assert payload["play_quota_bytes"] == 2 * 1024 * 1024


def test_enforce_play_quota_keeps_the_file_being_played(db_session, tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path)
    jobs = [Job(title=f"缓存 {index}", status="done") for index in range(3)]
    db_session.add_all(jobs)
    db_session.commit()
    files = []
    for index, job in enumerate(jobs):
        path = app_settings.job_workdir(job.id) / "play.mp4"
        _write(path, 1024 * 1024)
        stamp = 1_000_000 + index
        os.utime(path, (stamp, stamp))
        files.append(path)
    db_session.add(AppSetting(key="play_quota_mb", value="1"))
    db_session.commit()

    enforce_play_quota(db_session, protect_job_id=jobs[0].id)

    assert files[0].exists()
    assert not files[1].exists()
    assert not files[2].exists()


def test_play_quota_ignores_negative_value(client, db_session, tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path)
    job = Job(title="负数按不限制", status="done")
    db_session.add(job)
    db_session.commit()
    play = app_settings.job_workdir(job.id) / "play.mp4"
    _write(play, 2 * 1024 * 1024)

    response = client.put("/api/settings", json={"play_quota_mb": -5})
    assert response.json()["play_quota_mb"] == 0
    assert play.exists()
