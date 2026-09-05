from pathlib import Path
from threading import Lock
from urllib.parse import parse_qs, urlparse

from sqlalchemy.orm import Session

from app.config import settings
from app.models import Job
from app.services.authctx import build_auth
from app.services.ingest.base import ResolvedMedia
from app.services.ingest.registry import pick_adapter, resolve_media
from app.services.media import MediaError, remux_to_mp4

REFRESH_ADAPTERS = {"xiaoe", "yueniu", "bilibili"}
SIGN_KEYS = {"sign", "t", "token", "us", "auth_key", "txsecret", "pm3u8"}
BROWSER_VIDEO_EXTS = {".mp4", ".webm", ".mov", ".m4v", ".ogg", ".ogv"}
PROXY_HINTS = (".m4s", ".flv", "mcdn")
_play_locks: dict[str, Lock] = {}
_play_locks_guard = Lock()


def is_http_url(url: str) -> bool:
    return urlparse(url or "").scheme in {"http", "https"}


def looks_expiring(url: str) -> bool:
    query = {key.lower() for key in parse_qs(urlparse(url or "").query)}
    return bool(query & SIGN_KEYS)


def should_refresh_media(job: Job, adapter: str) -> bool:
    if not is_http_url(job.source_url):
        return False
    if adapter in REFRESH_ADAPTERS:
        return True
    return looks_expiring(job.media_url)


def play_endpoint(job_id: str) -> str:
    return f"/api/jobs/{job_id}/play"


def cached_play_file(job_id: str) -> Path | None:
    path = settings.uploads_path() / job_id / "play.mp4"
    if path.is_file() and path.stat().st_size > 0:
        return path
    return None


def local_video_file(job: Job) -> Path | None:
    for raw in (job.source_path, job.media_url, job.source_url):
        text = (raw or "").strip()
        if not text or is_http_url(text):
            continue
        path = Path(text)
        if path.is_file() and path.stat().st_size > 0:
            return path
    return None


def needs_play_proxy(media_url: str, adapter: str, source_type: str = "") -> bool:
    if adapter == "bilibili":
        return True
    text = (media_url or "").strip()
    if not text:
        return False
    if not is_http_url(text):
        return True
    lowered = text.lower()
    if ".m3u8" in lowered:
        return False
    if any(hint in lowered for hint in PROXY_HINTS):
        return True
    if source_type == "http_audio":
        return True
    return False


def browser_playback_url(
    job: Job,
    media_url: str,
    adapter: str,
    resolved: ResolvedMedia | None = None,
) -> str:
    if cached_play_file(job.id) or local_video_file(job):
        return play_endpoint(job.id)
    source_type = resolved.source_type if resolved else job.source_type
    if needs_play_proxy(media_url, adapter, source_type):
        return play_endpoint(job.id)
    return (media_url or "").strip()


def refresh_job_media(db: Session, job: Job) -> tuple[str, bool, str]:
    """忽略过期的媒体覆盖，按页面地址重新解析带签名的播放地址。"""
    current = (job.media_url or "").strip()
    adapter = _adapter_name(db, job)
    if not should_refresh_media(job, adapter):
        return browser_playback_url(job, current, adapter), False, ""
    auth = build_auth(
        db,
        url=job.source_url,
        site_id=job.site_id,
        auth_profile_id=job.auth_profile_id,
    )
    try:
        resolved = resolve_media(job.source_url, auth, media_url_override="")
    except Exception as exc:
        return (
            browser_playback_url(job, current, adapter),
            False,
            f"刷新播放地址失败：{exc}",
        )
    if not (resolved.media_url or "").strip():
        hint = resolved.message or "未能刷新播放地址，请确认站点登录 Cookie 仍有效。"
        return browser_playback_url(job, current, adapter, resolved), False, hint
    fresh = resolved.media_url.strip()
    if fresh != current:
        job.media_url = fresh
        db.add(job)
        db.commit()
        db.refresh(job)
    return browser_playback_url(job, fresh, adapter, resolved), True, ""


def ensure_play_file(db: Session, job: Job) -> Path:
    """生成本地可播 MP4；B 站等防盗链地址不能给浏览器直连。"""
    lock = _job_play_lock(job.id)
    with lock:
        cached = cached_play_file(job.id)
        if cached is not None:
            return cached
        local = local_video_file(job)
        if local is not None and local.suffix.lower() in BROWSER_VIDEO_EXTS:
            return local
        auth = build_auth(
            db,
            url=job.source_url,
            site_id=job.site_id,
            auth_profile_id=job.auth_profile_id,
        )
        source = (job.source_url or job.media_url or "").strip()
        resolved = resolve_media(source, auth, media_url_override=job.media_url_override)
        extra = resolved.extra or {}
        video_url = str(extra.get("play_video_url") or resolved.media_url or job.media_url or "").strip()
        audio_url = str(extra.get("play_audio_url") or "").strip()
        if local is not None:
            sources = [str(local)]
        elif video_url:
            sources = [video_url]
            if audio_url and audio_url != video_url:
                sources.append(audio_url)
        else:
            raise MediaError(resolved.message or "没有可播放的视频地址")
        dest = settings.job_workdir(job.id) / "play.mp4"
        try:
            return remux_to_mp4(sources, dest, extra_headers=resolved.headers)
        except MediaError:
            if len(sources) > 1:
                return remux_to_mp4([sources[0]], dest, extra_headers=resolved.headers)
            raise


def _job_play_lock(job_id: str) -> Lock:
    with _play_locks_guard:
        return _play_locks.setdefault(job_id, Lock())


def _adapter_name(db: Session, job: Job) -> str:
    auth = build_auth(
        db,
        url=job.source_url,
        site_id=job.site_id,
        auth_profile_id=job.auth_profile_id,
    )
    if auth.adapter and auth.adapter != "generic":
        return auth.adapter
    return pick_adapter(job.source_url).name
