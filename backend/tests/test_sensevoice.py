from pathlib import Path
import threading

from app.schemas import AppSettingsOut, TranscriptSegment
from app.services.sensevoice import (
    VAD_MAXSEG_MS,
    _refine_sparse_segments,
    _sensevoice_cmd,
    _sensevoice_env,
    _time_windows,
    is_sensevoice_model,
    needs_resplit,
    parse_srt,
    shift_segments,
    start_sensevoice_prefetch,
    strip_sensevoice_tags,
    transcribe_wav,
)
from app.services.transcribe import (
    AutoTranscriber,
    FasterWhisperTranscriber,
    OpenAICompatibleTranscriber,
    SenseVoiceTranscriber,
    is_local_whisper_model,
)


def test_is_sensevoice_model():
    assert not is_sensevoice_model("")
    assert is_sensevoice_model("sensevoice-small-q8")
    assert is_sensevoice_model("SenseVoice-Small-GGUF")
    assert not is_sensevoice_model("whisper-1")
    assert not is_sensevoice_model("small")
    assert is_local_whisper_model("small")
    assert is_local_whisper_model("large-v3")
    assert not is_local_whisper_model("whisper-1")
    assert not is_local_whisper_model("sensevoice-small-q8")


def test_strip_sensevoice_tags():
    assert strip_sensevoice_tags("<|zh|><|NEUTRAL|><|Speech|><|woitn|>大家好") == "大家好"
    assert strip_sensevoice_tags("没有标签") == "没有标签"


def test_parse_srt_keeps_clocks_and_strips_tags():
    srt = """
1
00:00:01,000 --> 00:00:04,200
<|zh|><|NEUTRAL|><|Speech|><|woitn|>复盘今天盘面

2
00:00:04,200 --> 00:00:08,000
每一次调整都可以参与
"""
    segments = parse_srt(srt)
    assert len(segments) == 2
    assert segments[0].id == 0
    assert segments[0].start == 1.0
    assert segments[0].end == 4.2
    assert "复盘今天盘面" in segments[0].text
    assert "<|" not in segments[0].text
    assert segments[1].text.startswith("每一次调整")


def test_needs_resplit_flags_long_thin_segments():
    assert needs_resplit(TranscriptSegment(id=0, start=298.9, end=428.0, text="有没有快进"))
    assert needs_resplit(TranscriptSegment(id=1, start=0, end=30, text="字" * 40))
    assert not needs_resplit(TranscriptSegment(id=2, start=15.3, end=29.9, text="字" * 140))


def test_shift_segments_keeps_relative_span():
    moved = shift_segments([TranscriptSegment(id=0, start=0.5, end=8.5, text="开场")], 298.9)
    assert moved[0].start == 299.4
    assert moved[0].end == 307.4


def test_sensevoice_cmd_caps_vad_window(monkeypatch):
    monkeypatch.setattr("app.services.sensevoice.ensure_runtime_binary", lambda: Path("/bin/sensevoice"))
    monkeypatch.setattr("app.services.sensevoice.ensure_gguf_files", lambda: (Path("/m.gguf"), Path("/v.gguf")))
    cmd = _sensevoice_cmd(Path("/a.wav"))
    assert "--vad-maxseg" in cmd
    assert str(VAD_MAXSEG_MS) in cmd


def test_time_windows_cover_long_span():
    windows = _time_windows(298.9, 428.0, 12)
    assert windows[0][0] == 298.9
    assert windows[-1][1] == 428.0
    assert all(end - start <= 12.01 for start, end in windows)


def test_refine_replaces_thin_long_segment(monkeypatch):
    original = [
        TranscriptSegment(id=0, start=0, end=10, text="这段够密" * 8),
        TranscriptSegment(id=1, start=298.9, end=428.0, text="有没有快进"),
    ]

    def fake_range(_audio, start, end, _workdir, _vad, **_kwargs):
        if end - start > 20:
            return [TranscriptSegment(id=0, start=start, end=end, text="还是太长")]
        return [
            TranscriptSegment(id=0, start=start, end=min(end, start + 8), text="补回被丢掉的盘面复盘内容补回被丢掉的盘面复盘内容")
        ]

    monkeypatch.setattr("app.services.sensevoice._transcribe_range", fake_range)
    refined = _refine_sparse_segments(Path("/a.wav"), original)
    assert refined[0].text.startswith("这段够密")
    assert sum(len(item.text) for item in refined) > len(original[1].text)
    assert all(item.end - item.start <= 18 or len(item.text) > 20 for item in refined[1:])


def test_sensevoice_env_caps_threads():
    env = _sensevoice_env(4)
    assert env["GGML_N_THREADS"] == "4"
    assert env["OMP_NUM_THREADS"] == "4"
    assert env["VECLIB_MAXIMUM_THREADS"] == "4"


def test_transcribe_wav_skips_refine_when_fast(monkeypatch):
    called = {"refine": 0}
    monkeypatch.setattr(
        "app.services.sensevoice._run_sensevoice",
        lambda *args, **kwargs: [TranscriptSegment(id=0, start=0, end=40, text="有没有快进")],
    )

    def boom(*args, **kwargs):
        called["refine"] += 1
        return []

    monkeypatch.setattr("app.services.sensevoice._refine_sparse_segments", boom)
    out = transcribe_wav(Path("/a.wav"), threads=4, refine=False)
    assert called["refine"] == 0
    assert out[0].text == "有没有快进"


def test_auto_transcriber_routes_sensevoice(monkeypatch):
    called = {"sense": 0, "openai": 0, "whisper": 0}
    monkeypatch.setattr(SenseVoiceTranscriber, "transcribe", lambda self, audio, settings: called.__setitem__("sense", called["sense"] + 1) or [])
    monkeypatch.setattr(OpenAICompatibleTranscriber, "transcribe", lambda self, audio, settings: called.__setitem__("openai", called["openai"] + 1) or [])
    monkeypatch.setattr(FasterWhisperTranscriber, "transcribe", lambda self, audio, settings: called.__setitem__("whisper", called["whisper"] + 1) or [])
    AutoTranscriber().transcribe(
        Path("a.wav"),
        AppSettingsOut(transcribe_model="sensevoice-small-q8", transcribe_api_key="k"),
    )
    assert called == {"sense": 1, "openai": 0, "whisper": 0}
    AutoTranscriber().transcribe(
        Path("a.wav"),
        AppSettingsOut(transcribe_model="whisper-1", transcribe_api_key="k"),
    )
    assert called["openai"] == 1
    AutoTranscriber().transcribe(
        Path("a.wav"),
        AppSettingsOut(transcribe_model="small", transcribe_api_key="k"),
    )
    assert called["whisper"] == 1
    assert called["openai"] == 1
    AutoTranscriber().transcribe(
        Path("a.wav"),
        AppSettingsOut(transcribe_model="whisper-1"),
    )
    assert called["sense"] == 2
    assert called["openai"] == 1
    assert called["whisper"] == 1


def test_start_prefetch_skips_when_disabled(monkeypatch):
    monkeypatch.setattr("app.services.sensevoice.settings.prefetch_sensevoice", False)
    called = {"n": 0}
    monkeypatch.setattr("app.services.sensevoice.prefetch_sensevoice_assets", lambda: called.__setitem__("n", 1))
    assert start_sensevoice_prefetch("sensevoice-small-q8") is None
    assert called["n"] == 0


def test_start_prefetch_skips_non_sensevoice(monkeypatch):
    monkeypatch.setattr("app.services.sensevoice.settings.prefetch_sensevoice", True)
    called = {"n": 0}
    monkeypatch.setattr("app.services.sensevoice.prefetch_sensevoice_assets", lambda: called.__setitem__("n", 1))
    assert start_sensevoice_prefetch("small") is None
    assert called["n"] == 0


def test_start_prefetch_runs_in_background(monkeypatch):
    monkeypatch.setattr("app.services.sensevoice.settings.prefetch_sensevoice", True)
    ready = threading.Event()

    def fake_prefetch():
        ready.set()

    monkeypatch.setattr("app.services.sensevoice.prefetch_sensevoice_assets", fake_prefetch)
    thread = start_sensevoice_prefetch("sensevoice-small-q8")
    assert thread is not None
    assert ready.wait(timeout=2)
    thread.join(timeout=2)
    assert not thread.is_alive()


def test_prefetch_assets_swallows_errors(monkeypatch):
    from app.services.sensevoice import prefetch_sensevoice_assets

    def boom():
        raise RuntimeError("网络断开")

    monkeypatch.setattr("app.services.sensevoice.ensure_runtime_binary", boom)
    prefetch_sensevoice_assets()


def test_prefetch_flag_constructor(tmp_path):
    from app.config import Settings

    assert Settings(data_dir=tmp_path, prefetch_sensevoice=True).prefetch_sensevoice is True
    assert Settings(data_dir=tmp_path, prefetch_sensevoice=False).prefetch_sensevoice is False
