import logging
import os
import platform
import re
import shutil
import subprocess
import tarfile
import tempfile
import threading
import wave
import zipfile
from pathlib import Path
from urllib.request import urlopen

from app.config import settings
from app.schemas import TranscriptSegment
from app.services.cancel import JobCancelled, raise_if_cancelled, register_process, unregister_process
from app.services.textnorm import normalize_transcript

logger = logging.getLogger(__name__)
_ASSET_LOCK = threading.Lock()
_RUN_LOCK = threading.RLock()
_THREAD_ENV_KEYS = (
    "GGML_N_THREADS",
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
    "MKL_NUM_THREADS",
)

RUNTIME_TAG = "runtime-llamacpp-v0.2.5"
RUNTIME_BASE = f"https://github.com/modelscope/FunASR/releases/download/{RUNTIME_TAG}"
SENSEVOICE_REPO = "FunAudioLLM/SenseVoiceSmall-GGUF"
VAD_REPO = "FunAudioLLM/fsmn-vad-GGUF"
SENSEVOICE_FILE = "sensevoice-small-q8.gguf"
VAD_FILE = "fsmn-vad.gguf"
MODEL_ALIASES = {"sensevoice-small-q8", "sensevoice-small-gguf", "sensevoice-small-gguf-q8", "sensevoice"}
# GGUF 路径超过约 15 秒会丢掉后半段；VAD 默认 30 秒，长课会出现 40–129 秒空壳片段
VAD_MAXSEG_MS = 15000
REFINE_VAD_MAXSEG_MS = 8000
FORCE_WINDOW_SECONDS = 12.0
OVERLONG_SECONDS = 18.0
THIN_MIN_SECONDS = 8.0
THIN_MAX_CPS = 3.2

SRT_CLOCK = re.compile(
    r"(\d{1,2}:\d{2}:\d{2}[,.]\d{1,3})\s*-->\s*(\d{1,2}:\d{2}:\d{2}[,.]\d{1,3})"
)
SENSEVOICE_TAG = re.compile(r"<\|[^|]+\|>")


class SenseVoiceError(RuntimeError):
    pass


def is_sensevoice_model(name: str) -> bool:
    normalized = (name or "").strip().lower().replace("_", "-")
    if not normalized:
        return False
    return "sensevoice" in normalized or normalized in MODEL_ALIASES


def parse_srt_clock(value: str) -> float:
    raw = value.strip().replace(",", ".")
    parts = raw.split(":")
    if len(parts) != 3:
        raise SenseVoiceError(f"无法解析 SRT 时间：{value}")
    hours, minutes, seconds = parts
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def strip_sensevoice_tags(text: str) -> str:
    return SENSEVOICE_TAG.sub("", text or "").strip()


def parse_srt(text: str) -> list[TranscriptSegment]:
    segments: list[TranscriptSegment] = []
    blocks = re.split(r"\n\s*\n", (text or "").replace("\r\n", "\n").strip())
    for block in blocks:
        lines = [line.strip() for line in block.split("\n") if line.strip()]
        if len(lines) < 2:
            continue
        clock_at = 0
        match = SRT_CLOCK.search(lines[0])
        if not match and len(lines) >= 2:
            match = SRT_CLOCK.search(lines[1])
            clock_at = 1
        if not match:
            continue
        body = " ".join(lines[clock_at + 1 :])
        cleaned = normalize_transcript(strip_sensevoice_tags(body))
        if not cleaned:
            continue
        start = parse_srt_clock(match.group(1))
        end = parse_srt_clock(match.group(2))
        if end < start:
            end = start
        segments.append(TranscriptSegment(id=len(segments), start=start, end=end, text=cleaned))
    return segments


def segment_duration(segment: TranscriptSegment) -> float:
    return max(0.0, float(segment.end) - float(segment.start))


def needs_resplit(segment: TranscriptSegment) -> bool:
    duration = segment_duration(segment)
    chars = len(segment.text or "")
    if duration >= OVERLONG_SECONDS:
        return True
    return duration >= THIN_MIN_SECONDS and chars / duration < THIN_MAX_CPS


def shift_segments(segments: list[TranscriptSegment], offset: float) -> list[TranscriptSegment]:
    return [
        item.model_copy(update={"start": item.start + offset, "end": item.end + offset})
        for item in segments
    ]


def reindex_segments(segments: list[TranscriptSegment]) -> list[TranscriptSegment]:
    return [item.model_copy(update={"id": index}) for index, item in enumerate(segments)]


def _time_windows(start: float, end: float, window: float = FORCE_WINDOW_SECONDS) -> list[tuple[float, float]]:
    spans: list[tuple[float, float]] = []
    cursor = start
    while cursor < end - 0.25:
        nxt = min(end, cursor + window)
        if nxt - cursor >= 0.25:
            spans.append((cursor, nxt))
        cursor = nxt
    return spans


def slice_wav(src: Path, dest: Path, start: float, end: float) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(src), "rb") as reader:
        rate = reader.getframerate()
        channels = reader.getnchannels()
        width = reader.getsampwidth()
        start_frame = max(0, int(start * rate))
        end_frame = min(reader.getnframes(), int(end * rate))
        reader.setpos(start_frame)
        frames = reader.readframes(max(0, end_frame - start_frame))
    with wave.open(str(dest), "wb") as writer:
        writer.setparams((channels, width, rate, 0, "NONE", "not compressed"))
        writer.writeframes(frames)
    if dest.stat().st_size <= 44:
        raise SenseVoiceError("切片音频为空")
    return dest


def _runtime_archive() -> str:
    system = platform.system().lower()
    machine = platform.machine().lower()
    if system == "darwin" and machine in {"arm64", "aarch64"}:
        return "funasr-llamacpp-macos-arm64.tar.gz"
    if system == "linux" and machine in {"arm64", "aarch64"}:
        return "funasr-llamacpp-linux-arm64.tar.gz"
    if system == "linux":
        return "funasr-llamacpp-linux-x64.tar.gz"
    if system == "windows":
        return "funasr-llamacpp-windows-x64.zip"
    raise SenseVoiceError(f"当前系统暂不支持 SenseVoice GGUF：{system} {machine}")


def _models_root() -> Path:
    path = settings.models_path() / "funasr-gguf"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _runtime_root() -> Path:
    path = settings.models_path() / "funasr-llamacpp"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _find_binary(root: Path) -> Path | None:
    names = {"llama-funasr-sensevoice", "llama-funasr-sensevoice.exe"}
    if root.is_file() and root.name in names:
        return root
    for item in root.rglob("*"):
        if item.is_file() and item.name in names:
            return item
    return None


def _download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    curl = shutil.which("curl")
    if curl:
        subprocess.run(
            [curl, "-fL", "--retry", "5", "--retry-delay", "2", "--connect-timeout", "30", "-o", str(tmp), url],
            check=True,
        )
    else:
        with urlopen(url, timeout=120) as response, tmp.open("wb") as handle:
            shutil.copyfileobj(response, handle)
    tmp.replace(dest)


def _extract_archive(archive: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    if archive.suffix == ".zip":
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(dest)
        return
    with tarfile.open(archive, "r:gz") as tf:
        tf.extractall(dest)


def _ensure_runtime_binary_unlocked() -> Path:
    found = shutil.which("llama-funasr-sensevoice")
    if found:
        return Path(found)
    existing = _find_binary(_runtime_root())
    if existing:
        return existing
    raise_if_cancelled()
    archive_name = _runtime_archive()
    archive = _runtime_root() / archive_name
    try:
        _download(f"{RUNTIME_BASE}/{archive_name}", archive)
        _extract_archive(archive, _runtime_root())
    except Exception as exc:
        raise SenseVoiceError(f"下载 SenseVoice 运行时失败：{exc}") from exc
    binary = _find_binary(_runtime_root())
    if binary is None:
        raise SenseVoiceError("运行时压缩包里没有 llama-funasr-sensevoice")
    if platform.system().lower() != "windows":
        binary.chmod(binary.stat().st_mode | 0o111)
    return binary


def ensure_runtime_binary() -> Path:
    with _ASSET_LOCK:
        return _ensure_runtime_binary_unlocked()


def _ensure_gguf_files_unlocked() -> tuple[Path, Path]:
    root = _models_root()
    model = root / SENSEVOICE_FILE
    vad = root / VAD_FILE
    if model.exists() and vad.exists():
        return model, vad
    try:
        from huggingface_hub import hf_hub_download
    except ImportError as exc:
        raise SenseVoiceError("未安装 huggingface_hub，无法下载 SenseVoice GGUF") from exc
    raise_if_cancelled()
    try:
        model_path = Path(
            hf_hub_download(SENSEVOICE_REPO, SENSEVOICE_FILE, local_dir=str(root))
        )
        vad_path = Path(hf_hub_download(VAD_REPO, VAD_FILE, local_dir=str(root)))
    except Exception as exc:
        raise SenseVoiceError(f"下载 SenseVoice GGUF 失败：{exc}") from exc
    return model_path, vad_path


def ensure_gguf_files() -> tuple[Path, Path]:
    with _ASSET_LOCK:
        return _ensure_gguf_files_unlocked()


def prefetch_sensevoice_assets() -> None:
    """下载运行时与 GGUF；已存在则立即返回。失败只记日志，首次转写还会再试。"""
    try:
        ensure_runtime_binary()
        ensure_gguf_files()
        logger.info("SenseVoice 运行时与权重已就绪")
    except Exception:
        logger.exception("SenseVoice 后台预拉失败，首次转写时会再试")


def start_sensevoice_prefetch(transcribe_model: str = "") -> threading.Thread | None:
    if not settings.prefetch_sensevoice:
        return None
    model = (transcribe_model or "").strip() or settings.default_transcribe_model
    if not is_sensevoice_model(model):
        logger.info("当前转写模型不是 SenseVoice，跳过后台预拉")
        return None
    thread = threading.Thread(target=prefetch_sensevoice_assets, name="sensevoice-prefetch", daemon=True)
    thread.start()
    logger.info("已在后台预拉 SenseVoice 运行时与权重")
    return thread


def _sensevoice_cmd(audio_path: Path, vad_maxseg_ms: int = VAD_MAXSEG_MS) -> list[str]:
    binary = ensure_runtime_binary()
    model, vad = ensure_gguf_files()
    return [
        str(binary),
        "-m",
        str(model),
        "--vad",
        str(vad),
        "--vad-maxseg",
        str(int(vad_maxseg_ms)),
        "-a",
        str(audio_path),
        "--srt",
    ]


def _thread_count(threads: int | None) -> int:
    if threads and threads > 0:
        return int(threads)
    n = max(1, os.cpu_count() or 1)
    return max(1, min(n, int(n * 0.8) or 1))


def _sensevoice_env(threads: int | None) -> dict[str, str]:
    env = os.environ.copy()
    value = str(_thread_count(threads))
    for key in _THREAD_ENV_KEYS:
        env[key] = value
    return env


def _run_sensevoice(
    audio_path: Path,
    vad_maxseg_ms: int = VAD_MAXSEG_MS,
    threads: int | None = None,
) -> list[TranscriptSegment]:
    raise_if_cancelled()
    cmd = _sensevoice_cmd(audio_path, vad_maxseg_ms)
    with _RUN_LOCK:
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=_sensevoice_env(threads),
            )
        except OSError as exc:
            raise SenseVoiceError(f"无法启动 SenseVoice：{exc}") from exc
        register_process(proc)
        stdout = ""
        stderr = ""
        try:
            while True:
                raise_if_cancelled()
                try:
                    stdout, stderr = proc.communicate(timeout=0.5)
                    break
                except subprocess.TimeoutExpired:
                    continue
        except JobCancelled:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=5)
            raise
        finally:
            unregister_process()
    raise_if_cancelled()
    if proc.returncode != 0:
        detail = ((stderr or stdout) or "").strip()[-800:]
        raise SenseVoiceError(f"SenseVoice 转写失败：{detail}")
    segments = parse_srt(stdout)
    if segments:
        return segments
    fallback = normalize_transcript(strip_sensevoice_tags((stdout or "").strip()))
    if fallback:
        return [TranscriptSegment(id=0, start=0, end=0, text=fallback)]
    return []


def _transcribe_range(
    audio_path: Path,
    start: float,
    end: float,
    workdir: Path,
    vad_maxseg_ms: int,
    threads: int | None = None,
) -> list[TranscriptSegment]:
    clip = workdir / f"clip-{int(start * 1000)}-{int(end * 1000)}.wav"
    slice_wav(audio_path, clip, start, end)
    return shift_segments(_run_sensevoice(clip, vad_maxseg_ms, threads=threads), start)


def _refine_sparse_segments(
    audio_path: Path,
    segments: list[TranscriptSegment],
    threads: int | None = None,
) -> list[TranscriptSegment]:
    if not any(needs_resplit(item) for item in segments):
        return segments
    refined: list[TranscriptSegment] = []
    with tempfile.TemporaryDirectory(prefix="sensevoice-refine-") as tmp:
        workdir = Path(tmp)
        for item in segments:
            if not needs_resplit(item):
                refined.append(item)
                continue
            raise_if_cancelled()
            try:
                pieces = _transcribe_range(
                    audio_path, item.start, item.end, workdir, REFINE_VAD_MAXSEG_MS, threads=threads
                )
            except SenseVoiceError:
                refined.append(item)
                continue
            if any(needs_resplit(piece) for piece in pieces) or sum(len(piece.text) for piece in pieces) <= len(item.text):
                forced: list[TranscriptSegment] = []
                for win_start, win_end in _time_windows(item.start, item.end):
                    raise_if_cancelled()
                    try:
                        forced.extend(
                            _transcribe_range(
                                audio_path, win_start, win_end, workdir, REFINE_VAD_MAXSEG_MS, threads=threads
                            )
                        )
                    except SenseVoiceError:
                        continue
                if sum(len(piece.text) for piece in forced) > max(len(item.text), sum(len(piece.text) for piece in pieces)):
                    pieces = forced
            if sum(len(piece.text) for piece in pieces) > len(item.text):
                refined.extend(pieces)
            else:
                refined.append(item)
    return reindex_segments(refined)


def transcribe_wav(
    audio_path: Path,
    threads: int | None = None,
    refine: bool = True,
) -> list[TranscriptSegment]:
    workers = _thread_count(threads)
    segments = _run_sensevoice(audio_path, VAD_MAXSEG_MS, threads=workers)
    if not segments:
        raise SenseVoiceError("SenseVoice 转写结果为空")
    if not refine:
        return segments
    return _refine_sparse_segments(audio_path, segments, threads=workers)
