import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

from app.config import settings
from app.services.cancel import JobCancelled, raise_if_cancelled, register_process, unregister_process


class MediaError(RuntimeError):
    pass


class MediaExtractor:
    def extract_audio(
        self,
        source: str,
        output_wav: Path,
        extra_headers: dict[str, str] | None = None,
        max_seconds: int | None = None,
    ) -> Path:
        raise NotImplementedError


def resolve_ffmpeg() -> str:
    found = shutil.which(settings.ffmpeg_bin)
    if found:
        return found
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as exc:
        raise MediaError("未找到 ffmpeg，请安装 ffmpeg 或 imageio-ffmpeg") from exc


def is_network_source(source: str) -> bool:
    lowered = (source or "").strip().lower()
    return lowered.startswith("http://") or lowered.startswith("https://")


def build_extract_cmd(
    ffmpeg_bin: str,
    source: str,
    output_wav: Path,
    extra_headers: dict[str, str] | None = None,
    max_seconds: int | None = None,
    *,
    map_audio: bool = True,
    reconnect: bool | None = None,
) -> list[str]:
    """只抽音轨；网络源带重连，避免把 HLS 视频分片也拉完。"""
    cmd = [ffmpeg_bin, "-hide_banner", "-nostdin", "-y"]
    use_reconnect = is_network_source(source) if reconnect is None else reconnect
    if use_reconnect:
        cmd.extend(
            [
                "-reconnect",
                "1",
                "-reconnect_streamed",
                "1",
                "-reconnect_delay_max",
                "2",
            ]
        )
    if extra_headers:
        header_text = "".join(f"{key}: {value}\r\n" for key, value in extra_headers.items())
        cmd.extend(["-headers", header_text])
    cmd.extend(["-i", source])
    if max_seconds and max_seconds > 0:
        cmd.extend(["-t", str(max_seconds)])
    if map_audio:
        cmd.extend(["-map", "0:a:0"])
    cmd.extend(
        [
            "-vn",
            "-sn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-c:a",
            "pcm_s16le",
            str(output_wav),
        ]
    )
    return cmd


class FfmpegExtractor(MediaExtractor):
    def extract_audio(
        self,
        source: str,
        output_wav: Path,
        extra_headers: dict[str, str] | None = None,
        max_seconds: int | None = None,
    ) -> Path:
        ffmpeg_bin = resolve_ffmpeg()
        output_wav.parent.mkdir(parents=True, exist_ok=True)
        mapped = build_extract_cmd(
            ffmpeg_bin,
            source,
            output_wav,
            extra_headers=extra_headers,
            max_seconds=max_seconds,
            map_audio=True,
        )
        try:
            return self._run(mapped, output_wav)
        except MediaError:
            if not any(item == "0:a:0" for item in mapped):
                raise
            fallback = build_extract_cmd(
                ffmpeg_bin,
                source,
                output_wav,
                extra_headers=extra_headers,
                max_seconds=max_seconds,
                map_audio=False,
            )
            return self._run(fallback, output_wav)

    def _run(self, cmd: list[str], output_wav: Path) -> Path:
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        except OSError as exc:
            raise MediaError(f"无法启动 ffmpeg：{exc}") from exc
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
            raise MediaError(f"ffmpeg 抽音失败：{detail}")
        if not output_wav.exists() or output_wav.stat().st_size == 0:
            raise MediaError("ffmpeg 未生成有效音频")
        return output_wav


def probe_creation_time(source: str) -> datetime | None:
    from app.services.sourcetime import parse_source_datetime

    try:
        ffmpeg_bin = resolve_ffmpeg()
    except MediaError:
        return None
    try:
        proc = subprocess.run(
            [ffmpeg_bin, "-hide_banner", "-i", source],
            capture_output=True,
            text=True,
            timeout=3,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    match = re.search(r"creation_time\s*:\s*(\S+)", proc.stderr or "")
    if not match:
        return None
    return parse_source_datetime(match.group(1))


def build_remux_cmd(
    ffmpeg_bin: str,
    sources: list[str],
    output: Path,
    extra_headers: dict[str, str] | None = None,
) -> list[str]:
    """把音视频流无损转封装为可 seek 的 MP4，供浏览器回放。"""
    cmd = [ffmpeg_bin, "-hide_banner", "-nostdin", "-y"]
    header_text = ""
    if extra_headers:
        header_text = "".join(f"{key}: {value}\r\n" for key, value in extra_headers.items())
    for source in sources:
        if is_network_source(source):
            cmd.extend(
                [
                    "-reconnect",
                    "1",
                    "-reconnect_streamed",
                    "1",
                    "-reconnect_delay_max",
                    "2",
                ]
            )
            if header_text:
                cmd.extend(["-headers", header_text])
        cmd.extend(["-i", source])
    if len(sources) >= 2:
        cmd.extend(["-map", "0:v:0", "-map", "1:a:0"])
    cmd.extend(["-c", "copy", "-movflags", "+faststart", "-f", "mp4", str(output)])
    return cmd


def remux_to_mp4(
    sources: list[str],
    output: Path,
    extra_headers: dict[str, str] | None = None,
) -> Path:
    ffmpeg_bin = resolve_ffmpeg()
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp = output.with_name(output.stem + ".tmp.mp4")
    if tmp.exists():
        tmp.unlink()
    cmd = build_remux_cmd(ffmpeg_bin, sources, tmp, extra_headers=extra_headers)
    extractor = FfmpegExtractor()
    try:
        extractor._run(cmd, tmp)
    except MediaError as exc:
        if tmp.exists():
            tmp.unlink()
        raise MediaError(str(exc).replace("抽音失败", "转封装失败").replace("有效音频", "可播放视频")) from exc
    if not tmp.exists() or tmp.stat().st_size == 0:
        raise MediaError("ffmpeg 未生成可播放视频")
    tmp.replace(output)
    return output


def default_extractor() -> MediaExtractor:
    return FfmpegExtractor()
