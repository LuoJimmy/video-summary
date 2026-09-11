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

        if Path(target).exists():
            path = Path(target).resolve()
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

        parsed = urlparse(target)
        if parsed.scheme == "file":
            path = Path(unquote(parsed.path)).resolve()
            source_type = local_source_type(path) if path.suffix else "local_file"
            created = None
            if path.exists():
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
