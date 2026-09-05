from app.services.authctx import RequestAuth
from app.services.ingest.base import ResolvedMedia, SiteAdapter
from app.services.ingest.bilibili import BilibiliAdapter
from app.services.ingest.generic import GenericAdapter
from app.services.ingest.xiaoe import XiaoeAdapter
from app.services.ingest.yueniu import YueniuAdapter

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
