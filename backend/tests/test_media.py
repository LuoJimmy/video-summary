from pathlib import Path

from app.services.media import FfmpegExtractor, MediaError, build_extract_cmd, build_remux_cmd, is_network_source


def test_is_network_source():
    assert is_network_source("https://cdn.example.com/a.m3u8")
    assert is_network_source("http://127.0.0.1/a.mp4")
    assert not is_network_source("/tmp/lecture.mp4")


def test_build_extract_cmd_maps_audio_and_reconnects_http():
    cmd = build_extract_cmd("ffmpeg", "https://cdn.example.com/live.m3u8", Path("/tmp/a.wav"))
    assert cmd[:4] == ["ffmpeg", "-hide_banner", "-nostdin", "-y"]
    assert "-reconnect" in cmd
    assert "-reconnect_streamed" in cmd
    i_at = cmd.index("-i")
    assert cmd[i_at + 1] == "https://cdn.example.com/live.m3u8"
    assert cmd.index("-reconnect") < i_at
    assert cmd[cmd.index("-map") + 1] == "0:a:0"
    assert "-vn" in cmd
    assert "-sn" in cmd
    assert cmd[cmd.index("-ar") + 1] == "16000"


def test_build_extract_cmd_skips_reconnect_for_local_file():
    cmd = build_extract_cmd("ffmpeg", "/data/a.mp4", Path("/tmp/a.wav"))
    assert "-reconnect" not in cmd
    assert "-map" in cmd


def test_build_remux_cmd_maps_video_and_audio():
    cmd = build_remux_cmd(
        "ffmpeg",
        ["https://upos.example.com/v.m4s", "https://upos.example.com/a.m4s"],
        Path("/tmp/play.mp4"),
        extra_headers={"Referer": "https://www.bilibili.com"},
    )
    assert cmd.count("-i") == 2
    assert cmd[cmd.index("-map") + 1] == "0:v:0"
    assert "1:a:0" in cmd
    assert "+faststart" in cmd
    assert cmd[cmd.index("-f") + 1] == "mp4"
    assert "-headers" in cmd
    assert "-reconnect" in cmd


def test_extract_retries_without_audio_map(monkeypatch, tmp_path):
    out = tmp_path / "audio.wav"
    calls: list[list[str]] = []

    class FakeProc:
        def __init__(self, cmd):
            calls.append(cmd)
            self.returncode = 1 if any(item == "0:a:0" for item in cmd) else 0

        def communicate(self, timeout=None):
            if self.returncode == 0:
                out.write_bytes(b"RIFF....")
            return "", "Stream map '0:a:0' matches no streams."

        def poll(self):
            return self.returncode

        def kill(self):
            return None

        def wait(self, timeout=None):
            return self.returncode

    monkeypatch.setattr("app.services.media.resolve_ffmpeg", lambda: "ffmpeg")
    monkeypatch.setattr("app.services.media.subprocess.Popen", lambda cmd, **kwargs: FakeProc(cmd))
    result = FfmpegExtractor().extract_audio("https://cdn.example.com/a.m3u8", out)
    assert result == out
    assert len(calls) == 2
    assert "0:a:0" in calls[0]
    assert "0:a:0" not in calls[1]


def test_extract_raises_when_both_attempts_fail(monkeypatch, tmp_path):
    out = tmp_path / "audio.wav"

    class FakeProc:
        returncode = 1

        def __init__(self, cmd):
            return None

        def communicate(self, timeout=None):
            return "", "boom"

        def poll(self):
            return 1

        def kill(self):
            return None

        def wait(self, timeout=None):
            return 1

    monkeypatch.setattr("app.services.media.resolve_ffmpeg", lambda: "ffmpeg")
    monkeypatch.setattr("app.services.media.subprocess.Popen", lambda cmd, **kwargs: FakeProc(cmd))
    try:
        FfmpegExtractor().extract_audio("/data/a.mp4", out)
        raise AssertionError("expected MediaError")
    except MediaError as exc:
        assert "抽音失败" in str(exc)
