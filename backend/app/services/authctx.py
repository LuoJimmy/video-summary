from dataclasses import dataclass, field
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from app.models import AuthProfile, Site
from app.services.jsonutil import loads


@dataclass
class RequestAuth:
    site: Site | None = None
    profile: AuthProfile | None = None
    cookie: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    adapter: str = "generic"


def _host_matches(host: str, pattern: str) -> bool:
    host = host.lower()
    pattern = pattern.lower().strip()
    if not pattern:
        return False
    if pattern == "*":
        return True
    if pattern.startswith("."):
        return host.endswith(pattern) or host == pattern[1:]
    return host == pattern or host.endswith("." + pattern)


def match_site(db: Session, url: str) -> Site | None:
    host = (urlparse(url).hostname or "").lower()
    if not host:
        return None
    sites = db.query(Site).filter(Site.enabled.is_(True)).all()
    ranked: list[tuple[int, Site]] = []
    for site in sites:
        patterns = loads(site.domain_patterns, [])
        for pattern in patterns:
            if _host_matches(host, str(pattern)):
                ranked.append((len(str(pattern)), site))
                break
    if not ranked:
        return None
    ranked.sort(key=lambda item: item[0], reverse=True)
    return ranked[0][1]


def build_auth(
    db: Session,
    url: str = "",
    site_id: str | None = None,
    auth_profile_id: str | None = None,
) -> RequestAuth:
    site = db.get(Site, site_id) if site_id else None
    if site is None and url:
        site = match_site(db, url)
    profile = None
    if auth_profile_id:
        profile = db.get(AuthProfile, auth_profile_id)
    elif site and site.auth_profile_id:
        profile = db.get(AuthProfile, site.auth_profile_id)

    headers: dict[str, str] = {}
    if profile:
        headers.update(loads(profile.extra_headers, {}))
    if site:
        headers.update(loads(site.extra_headers, {}))

    cookie = ""
    if profile and profile.cookie.strip():
        cookie = profile.cookie.strip()
    if site and site.cookie_override.strip():
        cookie = site.cookie_override.strip()

    return RequestAuth(
        site=site,
        profile=profile,
        cookie=cookie,
        headers=headers,
        adapter=site.adapter if site else "generic",
    )


def http_headers(auth: RequestAuth) -> dict[str, str]:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
        ),
        **auth.headers,
    }
    if auth.cookie:
        headers["Cookie"] = auth.cookie
    return headers
