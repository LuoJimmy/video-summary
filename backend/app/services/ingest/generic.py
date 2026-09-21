import re
from pathlib import Path
from urllib.parse import unquote, urlparse

from app.services.authctx import RequestAuth, http_headers
from app.services.ingest.base import (
    ResolvedMedia,
    SiteAdapter,
    classify_direct_url,
    is_document_ext,
    local_source_type,
)
from app.services.media import probe_creation_time
from app.services.sourcetime import file_created_at


_LOCAL_FILE_MISSING_HINT = (
    "容器里找不到这个本地文件。Docker 部署请在「本地任务」里选择挂载目录中的文件，"
    "或把宿主机目录挂到容器的 MEDIA_DIR；本机运行请检查路径拼写。"
)


def _local_media_path(target: str) -> Path | None:
    """容器里能直接读到的本地文件，才按本地媒体处理。"""
    path = Path(target)
    return path.resolve() if path.exists() else None


def _looks_like_local_path(target: str) -> bool:
    """以 / 或盘符开头的写法多半是本地路径；// 开头除外（协议相对 URL）。"""
    raw = (target or "").strip()
    if raw.startswith("//"):
        return False
    if raw.startswith("/") or raw.startswith("~/"):
        return True
    return bool(re.match(r"^[A-Za-z]:[\\/]", raw))


class GenericAdapter(SiteAdapter):
    name = "generic"

    def can_handle(self, url: str) -> bool:
        return True

    def resolve(self, url: str, auth: RequestAuth, media_url_override: str = "") -> ResolvedMedia:
        target = media_url_override.strip() or url.strip()
        if not target:
            return ResolvedMedia(
                adapter=self.name,
                source_type="unknown",
                needs_media_url=True,
                message="请提供本地文件、视频地址或 HLS 地址",
            )

        path = _local_media_path(target)
        if path is not None:
            source_type = local_source_type(path)
            created = file_created_at(path)
            if source_type == "local_file":
                created = probe_creation_time(str(path)) or created
            return ResolvedMedia(
                adapter=self.name,
                source_type=source_type,
                title=path.stem,
                media_url=str(path),
                headers=http_headers(auth),
                created_at=created,
                message="将提取文档正文" if source_type == "local_document" else "",
            )

        if _looks_like_local_path(target):
            return ResolvedMedia(
                adapter=self.name,
                source_type="unknown",
                needs_media_url=True,
                message=_LOCAL_FILE_MISSING_HINT,
            )

        parsed = urlparse(target)
        if parsed.scheme == "file":
            path = Path(unquote(parsed.path)).resolve()
            if not path.exists():
                return ResolvedMedia(
                    adapter=self.name,
                    source_type="unknown",
                    needs_media_url=True,
                    message=_LOCAL_FILE_MISSING_HINT,
                )
            source_type = local_source_type(path) if path.suffix else "local_file"
            created = file_created_at(path)
            if source_type == "local_file":
                created = probe_creation_time(str(path)) or created
            return ResolvedMedia(
                adapter=self.name,
                source_type=source_type,
                title=path.stem,
                media_url=str(path),
                headers=http_headers(auth),
                created_at=created,
            )

        source_type = classify_direct_url(target)
        if source_type == "page":
            source_type = "web_page"
            return ResolvedMedia(
                adapter=self.name,
                source_type=source_type,
                title=Path(parsed.path).stem or target,
                media_url=target,
                page_url=target,
                needs_media_url=False,
                message="将提取网页正文",
                headers=http_headers(auth),
            )
        if source_type == "http_document" or is_document_ext(target):
            return ResolvedMedia(
                adapter=self.name,
                source_type="http_document",
                title=Path(parsed.path).stem or target,
                media_url=target,
                page_url=target,
                needs_media_url=False,
                message="将下载并提取文档正文",
                headers=http_headers(auth),
            )
        return ResolvedMedia(
            adapter=self.name,
            source_type=source_type,
            title=Path(parsed.path).stem or target,
            media_url=target,
            headers=http_headers(auth),
        )
