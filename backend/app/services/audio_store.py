"""转写音频的归档：抽音得到 16kHz 单声道 WAV，转写完压成 opus 存档，重转写时再解回 WAV。

WAV 是 32KB/秒（1 小时约 115MB），opus 24kbps 约 3KB/秒，体积只有约十分之一。
SenseVoice 的切片（`slice_wav`）基于 wave 模块，只能读 PCM，所以要先解回 WAV 再转写。
"""

from pathlib import Path

from app.config import settings
from app.services.cancel import JobCancelled
from app.services.media import MediaError, resolve_ffmpeg, run_ffmpeg

WAV_NAME = "audio.wav"
ARCHIVE_NAME = "audio.opus"
ARCHIVE_BITRATE = "24k"


def wav_path(job_id: str) -> Path:
    return settings.job_workdir(job_id) / WAV_NAME


def archive_path(job_id: str) -> Path:
    return settings.job_workdir(job_id) / ARCHIVE_NAME


def has_job_audio(job_id: str) -> bool:
    for path in (wav_path(job_id), archive_path(job_id)):
        try:
            if path.is_file() and path.stat().st_size > 0:
                return True
        except OSError:
            continue
    return False


def build_archive_cmd(ffmpeg_bin: str, source: Path, output: Path) -> list[str]:
    """压成 16kHz 单声道 opus，放 ogg 容器；转写前能再解回 WAV。"""
    return [
        ffmpeg_bin,
        "-hide_banner",
        "-nostdin",
        "-y",
        "-i",
        str(source),
        "-vn",
        "-sn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-c:a",
        "libopus",
        "-b:a",
        ARCHIVE_BITRATE,
        "-f",
        "ogg",
        str(output),
    ]


def build_restore_cmd(ffmpeg_bin: str, source: Path, output: Path) -> list[str]:
    return [
        ffmpeg_bin,
        "-hide_banner",
        "-nostdin",
        "-y",
        "-i",
        str(source),
        "-vn",
        "-sn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-c:a",
        "pcm_s16le",
        str(output),
    ]


def archive_job_audio(job_id: str, wav: Path | None = None) -> Path | None:
    """把转写用的 WAV 压成 opus 存档，成功后才删 WAV；失败保留，下次仍可重转写。"""
    source = wav or wav_path(job_id)
    try:
        if not source.is_file() or source.stat().st_size <= 0:
            return None
    except OSError:
        return None
    dest = archive_path(job_id)
    tmp = dest.with_name(dest.name + ".part")
    if tmp.exists():
        tmp.unlink()
    try:
        run_ffmpeg(
            build_archive_cmd(resolve_ffmpeg(), source, tmp),
            tmp,
            label="音频归档",
            empty_message="ffmpeg 未生成有效音频归档",
        )
    except JobCancelled:
        tmp.unlink(missing_ok=True)
        raise
    except MediaError:
        tmp.unlink(missing_ok=True)
        return None
    tmp.replace(dest)
    try:
        source.unlink()
    except OSError:
        pass
    return dest


def materialize_job_audio(job_id: str, stored: str = "") -> Path:
    """返回可直接转写的 WAV：已有 WAV 直接用，只有 opus 存档时先解回；都没有则返回空路径位。"""
    target = settings.resolve_job_audio_path(job_id, stored)
    try:
        if target.is_file() and target.stat().st_size > 0:
            return target
    except OSError:
        pass
    archive = archive_path(job_id)
    try:
        if not archive.is_file() or archive.stat().st_size <= 0:
            return target
    except OSError:
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        run_ffmpeg(
            build_restore_cmd(resolve_ffmpeg(), archive, target),
            target,
            label="音频还原",
            empty_message="ffmpeg 未还原出有效音频",
        )
    except JobCancelled:
        target.unlink(missing_ok=True)
        raise
    except MediaError:
        target.unlink(missing_ok=True)
        return target
    return target
