import os
from pathlib import Path

os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

from app.schemas import AppSettingsOut, TranscriptSegment
from app.services.cancel import JobCancelled, raise_if_cancelled
from app.services.httpclient import openai_client
from app.services.sensevoice import SenseVoiceError, is_sensevoice_model, transcribe_wav
from app.services.settings_store import parse_transcribe_threads
from app.services.textnorm import normalize_transcript, whisper_hint


class TranscribeError(RuntimeError):
    pass


LOCAL_WHISPER_MODELS = {"tiny", "base", "small", "medium", "large", "large-v2", "large-v3"}


def is_local_whisper_model(name: str) -> bool:
    normalized = (name or "").strip().lower().replace("_", "-")
    return normalized in LOCAL_WHISPER_MODELS


def _resolve_local_whisper(model_name: str) -> str:
    from app.config import settings

    root = settings.models_path()
    requested = root / f"faster-whisper-{model_name}"
    if requested.exists():
        return str(requested)
    tiny = root / "faster-whisper-tiny"
    if tiny.exists():
        return str(tiny)
    return model_name


class Transcriber:
    def transcribe(self, audio_path: Path, settings: AppSettingsOut) -> list[TranscriptSegment]:
        raise NotImplementedError


def _segments_from_openai(result) -> list[TranscriptSegment]:
    raw_segments = getattr(result, "segments", None) or []
    segments: list[TranscriptSegment] = []
    if raw_segments:
        for item in raw_segments:
            if isinstance(item, dict):
                start = float(item.get("start") or 0)
                end = float(item.get("end") or start)
                text = str(item.get("text") or "").strip()
            else:
                start = float(getattr(item, "start", 0) or 0)
                end = float(getattr(item, "end", start) or start)
                text = str(getattr(item, "text", "") or "").strip()
            if not text:
                continue
            segments.append(TranscriptSegment(id=len(segments), start=start, end=end, text=normalize_transcript(text)))
        return segments
    text = str(getattr(result, "text", "") or "").strip()
    if not text:
        raise TranscribeError("转写结果为空")
    return [TranscriptSegment(id=0, start=0, end=0, text=normalize_transcript(text))]


class OpenAICompatibleTranscriber(Transcriber):
    def transcribe(self, audio_path: Path, settings: AppSettingsOut) -> list[TranscriptSegment]:
        if not settings.transcribe_api_key:
            raise TranscribeError("未配置转写 API Key")
        client = openai_client(settings.transcribe_api_key, settings.transcribe_base_url)
        raise_if_cancelled()
        with audio_path.open("rb") as handle:
            try:
                result = client.audio.transcriptions.create(
                    model=settings.transcribe_model or "whisper-1",
                    file=handle,
                    language="zh",
                    prompt=whisper_hint(),
                    response_format="verbose_json",
                    timestamp_granularities=["segment"],
                )
            except JobCancelled:
                raise
            except Exception as exc:
                raise TranscribeError(f"转写接口调用失败：{exc}") from exc
        return _segments_from_openai(result)


class SenseVoiceTranscriber(Transcriber):
    def transcribe(self, audio_path: Path, settings: AppSettingsOut) -> list[TranscriptSegment]:
        try:
            return transcribe_wav(
                audio_path,
                threads=parse_transcribe_threads(getattr(settings, "transcribe_threads", 0)),
                refine=not bool(getattr(settings, "transcribe_fast", False)),
            )
        except SenseVoiceError as exc:
            raise TranscribeError(str(exc)) from exc


class FasterWhisperTranscriber(Transcriber):
    def transcribe(self, audio_path: Path, settings: AppSettingsOut) -> list[TranscriptSegment]:
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise TranscribeError("未安装 faster-whisper，且未配置转写 API Key") from exc
        model_name = settings.transcribe_model if settings.transcribe_model not in {"", "whisper-1"} else "small"
        model_name = _resolve_local_whisper(model_name)
        threads = parse_transcribe_threads(getattr(settings, "transcribe_threads", 0))
        raise_if_cancelled()
        try:
            if Path(model_name).exists():
                os.environ["HF_HUB_OFFLINE"] = "1"
            model = WhisperModel(
                model_name,
                device="cpu",
                compute_type="int8",
                cpu_threads=threads,
                local_files_only=Path(model_name).exists(),
            )
            raise_if_cancelled()
            raw_segments, _info = model.transcribe(
                str(audio_path),
                language="zh",
                initial_prompt=whisper_hint(),
                vad_filter=True,
            )
        except JobCancelled:
            raise
        except Exception as exc:
            raise TranscribeError(f"本地 Whisper 转写失败：{exc}") from exc
        segments: list[TranscriptSegment] = []
        for item in raw_segments:
            raise_if_cancelled()
            text = (item.text or "").strip()
            if not text:
                continue
            segments.append(
                TranscriptSegment(
                    id=len(segments),
                    start=float(item.start or 0),
                    end=float(item.end or item.start or 0),
                    text=normalize_transcript(text),
                )
            )
        if not segments:
            raise TranscribeError("本地转写结果为空")
        return segments


class AutoTranscriber(Transcriber):
    def transcribe(self, audio_path: Path, settings: AppSettingsOut) -> list[TranscriptSegment]:
        model = settings.transcribe_model or ""
        if is_sensevoice_model(model):
            return SenseVoiceTranscriber().transcribe(audio_path, settings)
        if is_local_whisper_model(model):
            return FasterWhisperTranscriber().transcribe(audio_path, settings)
        if settings.transcribe_api_key:
            return OpenAICompatibleTranscriber().transcribe(audio_path, settings)
        return SenseVoiceTranscriber().transcribe(audio_path, settings)


def default_transcriber() -> Transcriber:
    return AutoTranscriber()
