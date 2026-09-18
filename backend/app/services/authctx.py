import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from app.models import AuthProfile, Site
from app.services.jsonutil import loads

_COOKIE_PREFIX_RE = re.compile(r"^\s*(?:cookie|set-cookie)\s*:\s*", re.I)
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_BAD_COOKIE_NAME_CHARS = " \t:,"


def normalize_header_value(raw: object) -> str:
    """请求头的值必须单行：换行/制表符折叠成空格，并去掉控制字符。"""
    return _CONTROL_CHARS_RE.sub("", " ".join(str(raw or "").split()))


def normalize_cookie(raw: object) -> str:
    """把粘贴进来的 Cookie 归一成单行 `name=value; name=value`。

    浏览器扩展导出的「Header String」常是每行一个 name=value，
    直接塞进 Cookie 头会被 httpx / h11 判成 Illegal header value。
    """
    text = str(raw or "")
    if "\\n" in text or "\\r" in text:
        # 从 JSON / JS 字符串里拷出来的换行是字面量 "\n"
        text = text.replace("\\r\\n", "\n").replace("\\r", "\n").replace("\\n", "\n")
    text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    text = _COOKIE_PREFIX_RE.sub("", text)
    pairs: list[str] = []
    for line in text.split("\n"):
        for item in line.split(";"):
            pair = _CONTROL_CHARS_RE.sub("", item).strip()
            if not pair or "=" not in pair:
                continue
            name, _, value = pair.partition("=")
            name = name.strip()
            if not name or any(char in name for char in _BAD_COOKIE_NAME_CHARS):
                continue
            pairs.append(f"{name}={value.strip()}")
    return "; ".join(pairs)


@dataclass
class RequestAuth:
    site: Site | None = None
    profile: AuthProfile | None = None
    cookie: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    adapter: str = "generic"

    def __post_init__(self) -> None:
        self.cookie = normalize_cookie(self.cookie)


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
        cookie = normalize_cookie(profile.cookie)
    if site and site.cookie_override.strip():
        cookie = normalize_cookie(site.cookie_override)

    return RequestAuth(
        site=site,
        profile=profile,
        cookie=cookie,
        headers=headers,
        adapter=site.adapter if site else "generic",
    )


def http_headers(auth: RequestAuth) -> dict[str, str]:
    headers: dict[str, str] = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
        ),
    }
    header_cookie = ""
    for key, value in (auth.headers or {}).items():
        name = str(key or "").strip().rstrip(":").strip()
        if not name:
            continue
        if name.lower() == "cookie":
            header_cookie = normalize_cookie(value)
            continue
        headers[name] = normalize_header_value(value)
    cookie = normalize_cookie(auth.cookie) or header_cookie
    if cookie:
        headers["Cookie"] = cookie
    return headers
