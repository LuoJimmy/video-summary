from datetime import datetime

from app.services.authctx import RequestAuth
from app.services.ingest.base import CatalogPage, CatalogRef, ResolvedMedia, SiteAdapter
from app.services.ingest.bilibili import BilibiliAdapter, detect_bilibili_catalog
from app.services.ingest.generic import GenericAdapter
from app.services.ingest.xiaoe import (
    XiaoeAdapter,
    detect_xiaoe_catalog,
    expand_xiaoe_short_link,
)
from app.services.ingest.yueniu import YueniuAdapter, detect_yueniu_catalog

ADAPTERS: dict[str, SiteAdapter] = {
    "generic": GenericAdapter(),
    "xiaoe": XiaoeAdapter(),
    "yueniu": YueniuAdapter(),
    "bilibili": BilibiliAdapter(),
}


def pick_adapter(url: str, preferred: str | None = None) -> SiteAdapter:
    if preferred and preferred in ADAPTERS and preferred != "generic":
        return ADAPTERS[preferred]
    for name, adapter in ADAPTERS.items():
        if name == "generic":
            continue
        if adapter.can_handle(url):
            return adapter
    return ADAPTERS["generic"]


def resolve_media(url: str, auth: RequestAuth, media_url_override: str = "") -> ResolvedMedia:
    adapter = pick_adapter(url, auth.adapter if auth.adapter != "generic" else None)
    return adapter.resolve(url, auth, media_url_override=media_url_override)


def detect_catalog(url: str) -> CatalogRef | None:
    text = (url or "").strip()
    if not text:
        return None
    adapter = pick_adapter(text)
    if adapter.name == "bilibili":
        return detect_bilibili_catalog(text)
    if adapter.name == "xiaoe":
        return detect_xiaoe_catalog(text)
    if adapter.name == "yueniu":
        return detect_yueniu_catalog(text)
    return detect_xiaoe_catalog(text) or detect_bilibili_catalog(text) or detect_yueniu_catalog(text)


def expand_catalog_short_link(url: str, auth: RequestAuth) -> str:
    """短链跟随：小鹅通 /sl/ 分享链要先跳转，才能判断是店铺还是单条内容。"""
    return expand_xiaoe_short_link(url, auth)


def list_catalog(
    adapter_name: str,
    auth: RequestAuth,
    catalog_id: str,
    since: datetime | None = None,
    cursor: str | None = None,
    limit: int | None = None,
) -> CatalogPage:
    adapter = ADAPTERS.get(adapter_name) or ADAPTERS["generic"]
    return adapter.list_catalog(auth, catalog_id, since=since, cursor=cursor, limit=limit)
