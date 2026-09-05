from pathlib import Path
from urllib.parse import unquote, urlparse

from app.services.authctx import RequestAuth, http_headers
from app.services.ingest.base import ResolvedMedia, SiteAdapter, classify_direct_url
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
            return ResolvedMedia(
                adapter=self.name,
                source_type="local_file",
                title=path.stem,
                media_url=str(path),
                headers=http_headers(auth),
                created_at=probe_creation_time(str(path)) or file_created_at(path),
            )

        parsed = urlparse(target)
        if parsed.scheme == "file":
            path = Path(unquote(parsed.path)).resolve()
            return ResolvedMedia(
                adapter=self.name,
                source_type="local_file",
                title=path.stem,
                media_url=str(path),
                headers=http_headers(auth),
                created_at=(probe_creation_time(str(path)) or file_created_at(path)) if path.exists() else None,
            )

        source_type = classify_direct_url(target)
        needs = source_type == "page"
        message = ""
        if needs:
            message = "该地址看起来是网页而不是媒体文件，请填写媒体地址覆盖，或改用对应站点适配器"
        return ResolvedMedia(
            adapter=self.name,
            source_type=source_type,
            title=Path(parsed.path).stem or target,
            media_url="" if needs else target,
            page_url=target if needs else "",
            needs_media_url=needs,
            message=message,
            headers=http_headers(auth),
        )
