from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

from app.services.authctx import RequestAuth


VIDEO_EXTS = {".mp4", ".mkv", ".mov", ".webm", ".avi", ".m4v", ".ts"}
AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}
HLS_HINTS = (".m3u8", "m3u8?")


@dataclass
class ResolvedMedia:
    adapter: str
    source_type: str
    title: str = ""
    media_url: str = ""
    page_url: str = ""
    needs_media_url: bool = False
    message: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    created_at: datetime | None = None
    extra: dict[str, Any] = field(default_factory=dict)


class SiteAdapter:
    name = "generic"

    def can_handle(self, url: str) -> bool:
        return False

    def resolve(self, url: str, auth: RequestAuth, media_url_override: str = "") -> ResolvedMedia:
        raise NotImplementedError


def classify_direct_url(url: str) -> str:
    lowered = url.lower()
    path = urlparse(url).path.lower()
    if any(hint in lowered for hint in HLS_HINTS):
        return "hls"
    if any(path.endswith(ext) for ext in VIDEO_EXTS):
        return "http_video"
    if any(path.endswith(ext) for ext in AUDIO_EXTS):
        return "http_audio"
    if url.startswith("file://") or (len(url) > 1 and url[1] == ":"):
        return "local_file"
    return "page"
