from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from app.services.authctx import RequestAuth


VIDEO_EXTS = {".mp4", ".mkv", ".mov", ".webm", ".avi", ".m4v", ".ts"}
AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}
DOCUMENT_EXTS = {".pdf", ".docx", ".doc", ".md", ".markdown", ".txt", ".html", ".htm"}
DOCUMENT_SOURCE_TYPES = {"local_document", "http_document", "web_page"}
HLS_HINTS = (".m3u8", "m3u8?")


class CatalogError(Exception):
    """站点内容列表失败，由调度器写入单站错误而不中断整轮。"""


@dataclass
class CatalogItem:
    source_url: str
    title: str = ""
    author: str = ""
    created_at: datetime | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class ResolvedMedia:
    adapter: str
    source_type: str
    title: str = ""
    author: str = ""
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

    def list_catalog(
        self,
        auth: RequestAuth,
        catalog_id: str,
        since: datetime | None = None,
    ) -> list[CatalogItem]:
        return []


def path_suffix(url: str) -> str:
    raw = (url or "").strip()
    if raw.startswith("file://"):
        raw = unquote(urlparse(raw).path)
    elif "://" in raw:
        raw = unquote(urlparse(raw).path)
    return Path(raw).suffix.lower()


def is_document_ext(url: str) -> bool:
    return path_suffix(url) in DOCUMENT_EXTS


def is_document_source(source_type: str) -> bool:
    return (source_type or "") in DOCUMENT_SOURCE_TYPES


def local_source_type(path: Path | str) -> str:
    suffix = Path(path).suffix.lower()
    if suffix in DOCUMENT_EXTS:
        return "local_document"
    return "local_file"


def classify_direct_url(url: str) -> str:
    lowered = url.lower()
    path = urlparse(url).path.lower()
    if any(hint in lowered for hint in HLS_HINTS):
        return "hls"
    if any(path.endswith(ext) for ext in VIDEO_EXTS):
        return "http_video"
    if any(path.endswith(ext) for ext in AUDIO_EXTS):
        return "http_audio"
    if any(path.endswith(ext) for ext in DOCUMENT_EXTS):
        return "http_document"
    if url.startswith("file://") or (len(url) > 1 and url[1] == ":"):
        return local_source_type(Path(unquote(urlparse(url).path) if url.startswith("file://") else url))
    return "page"
