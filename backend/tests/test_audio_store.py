from app.config import settings as app_settings
from app.services.audio_store import (
    ARCHIVE_NAME,
    WAV_NAME,
    archive_job_audio,
    build_archive_cmd,
    build_restore_cmd,
    has_job_audio,
    materialize_job_audio,
)
from app.services.media import MediaError


def test_build_archive_cmd_uses_opus_mono_16k(tmp_path):
    cmd = build_archive_cmd("ffmpeg", tmp_path / WAV_NAME, tmp_path / ARCHIVE_NAME)
    assert cmd[:4] == ["ffmpeg", "-hide_banner", "-nostdin", "-y"]
    assert cmd[cmd.index("-c:a") + 1] == "libopus"
    assert cmd[cmd.index("-ac") + 1] == "1"
    assert cmd[cmd.index("-ar") + 1] == "16000"
    assert cmd[cmd.index("-f") + 1] == "ogg"
    assert cmd[-1].endswith(ARCHIVE_NAME)


def test_build_restore_cmd_returns_pcm_wav(tmp_path):
    cmd = build_restore_cmd("ffmpeg", tmp_path / ARCHIVE_NAME, tmp_path / WAV_NAME)
    assert cmd[cmd.index("-c:a") + 1] == "pcm_s16le"
    assert cmd[-1].endswith(WAV_NAME)


def _isolate(monkeypatch, tmp_path):
    monkeypatch.setattr(app_settings, "data_dir", tmp_path)
    monkeypatch.setattr(app_settings, "download_dir", "")
    monkeypatch.setattr("app.services.audio_store.resolve_ffmpeg", lambda: "ffmpeg")


def test_archive_replaces_wav_with_opus(tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path)
    workdir = app_settings.job_workdir("job-archive")
    wav = workdir / WAV_NAME
    wav.write_bytes(b"RIFF" + b"\x00" * 32)

    def fake_run(cmd, output, **kwargs):
        output.write_bytes(b"OggS")
        return output

    monkeypatch.setattr("app.services.audio_store.run_ffmpeg", fake_run)
    archived = archive_job_audio("job-archive")
    assert archived == workdir / ARCHIVE_NAME
    assert archived.read_bytes() == b"OggS"
    assert not wav.exists()
    assert has_job_audio("job-archive")


def test_archive_keeps_wav_when_ffmpeg_fails(tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path)
    workdir = app_settings.job_workdir("job-failed")
    wav = workdir / WAV_NAME
    wav.write_bytes(b"RIFF" + b"\x00" * 32)

    def boom(cmd, output, **kwargs):
        raise MediaError("ffmpeg 音频归档失败：libopus missing")

    monkeypatch.setattr("app.services.audio_store.run_ffmpeg", boom)
    assert archive_job_audio("job-failed") is None
    assert wav.exists()
    assert not (workdir / ARCHIVE_NAME).exists()
    assert not (workdir / f"{ARCHIVE_NAME}.part").exists()


def test_archive_skips_missing_wav(tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path)
    assert archive_job_audio("job-empty") is None
    assert not app_settings.job_workdir("job-empty").joinpath(ARCHIVE_NAME).exists()


def test_materialize_restores_from_archive(tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path)
    workdir = app_settings.job_workdir("job-restore")
    archive = workdir / ARCHIVE_NAME
    archive.write_bytes(b"OggS")
    calls: list[list[str]] = []

    def fake_run(cmd, output, **kwargs):
        calls.append(cmd)
        output.write_bytes(b"RIFF" + b"\x00" * 16)
        return output

    monkeypatch.setattr("app.services.audio_store.run_ffmpeg", fake_run)
    path = materialize_job_audio("job-restore")
    assert path == workdir / WAV_NAME
    assert path.read_bytes().startswith(b"RIFF")
    assert calls and calls[0][-1].endswith(WAV_NAME)


def test_materialize_keeps_existing_wav(tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path)
    workdir = app_settings.job_workdir("job-wav")
    wav = workdir / WAV_NAME
    wav.write_bytes(b"RIFF" + b"\x00" * 16)
    calls: list[list[str]] = []
    monkeypatch.setattr(
        "app.services.audio_store.run_ffmpeg",
        lambda cmd, output, **kwargs: calls.append(cmd) or output,
    )
    assert materialize_job_audio("job-wav") == wav
    assert calls == []


def test_materialize_without_audio_returns_missing_path(tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path)
    path = materialize_job_audio("job-none")
    assert path == app_settings.job_workdir("job-none") / WAV_NAME
    assert not path.exists()


def test_materialize_drops_broken_restore(tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path)
    workdir = app_settings.job_workdir("job-broken")
    (workdir / ARCHIVE_NAME).write_bytes(b"OggS")

    def broken(cmd, output, **kwargs):
        output.write_bytes(b"")
        raise MediaError("ffmpeg 音频还原失败")

    monkeypatch.setattr("app.services.audio_store.run_ffmpeg", broken)
    path = materialize_job_audio("job-broken")
    assert not path.exists()
