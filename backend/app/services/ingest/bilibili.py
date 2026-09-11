import hashlib
import json
import re
import time
from datetime import datetime
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

from app.services.authctx import RequestAuth, http_headers
from app.services.httpclient import http_client
from app.services.ingest.base import CatalogError, CatalogItem, ResolvedMedia, SiteAdapter, classify_direct_url
from app.services.sourceauthor import normalize_author
from app.services.sourcetime import pick_source_datetime

BILI_HOSTS = ("bilibili.com", "b23.tv", "bili2233.cn")
VIEW_API = "https://api.bilibili.com/x/web-interface/view"
NAV_API = "https://api.bilibili.com/x/web-interface/nav"
PLAY_API = "https://api.bilibili.com/x/player/playurl"
PLAY_WBI_API = "https://api.bilibili.com/x/player/wbi/playurl"
SPACE_SEARCH_API = "https://api.bilibili.com/x/space/arc/search"
SPACE_WBI_API = "https://api.bilibili.com/x/space/wbi/arc/search"
BVID_RE = re.compile(r"(BV[0-9A-Za-z]{10})", re.I)
AV_RE = re.compile(r"(?:/video/)?av(\d+)", re.I)
MID_RE = re.compile(r"space\.bilibili\.com/(\d+)", re.I)
PAGE_PAUSE = 0.8
RETRY_BACKOFF = (2.0, 5.0, 10.0)
MAX_SPACE_PAGES = 3
RATE_LIMIT_CODES = {-799, -412, 412, -352, -509}
RATE_LIMIT_STATUSES = {412, 429, 503}
WBI_MIXIN_INDEX = (
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35, 27, 43, 5, 49,
    33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13, 37, 48, 7, 16, 24, 55, 40,
    61, 26, 17, 0, 1, 60, 51, 30, 4, 22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11,
    36, 20, 34, 44, 52,
)


def is_bili_rate_limited(code=None, message: str = "", status_code: int | None = None) -> bool:
    if status_code in RATE_LIMIT_STATUSES:
        return True
    try:
        code_int = int(code) if code is not None and code != "" else None
    except (TypeError, ValueError):
        code_int = None
    if code_int in RATE_LIMIT_CODES:
        return True
    text = message or ""
    lowered = text.lower()
    return (
        "频繁" in text
        or "稍后再试" in text
        or "限流" in text
        or "too many" in lowered
        or "rate limit" in lowered
    )


def parse_bilibili_ref(url: str) -> tuple[str, str, int]:
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    try:
        page = max(1, int((query.get("p") or ["1"])[0] or 1))
    except ValueError:
        page = 1
    bvid_match = BVID_RE.search(url)
    bvid = bvid_match.group(1) if bvid_match else ""
    if bvid.startswith("bv"):
        bvid = "BV" + bvid[2:]
    aid_match = AV_RE.search(parsed.path)
    aid = aid_match.group(1) if aid_match else ""
    return bvid, aid, page


def parse_bilibili_mid(catalog_id: str) -> str:
    text = (catalog_id or "").strip()
    if re.fullmatch(r"\d+", text):
        return text
    match = MID_RE.search(text)
    if match:
        return match.group(1)
    query = parse_qs(urlparse(text).query)
    mid = (query.get("mid") or [""])[0].strip()
    return mid if mid.isdigit() else ""


def _https(url: str) -> str:
    if url.startswith("http://"):
        return "https://" + url[7:]
    return url


def _wbi_filename(url: str) -> str:
    name = str(url or "").rsplit("/", 1)[-1]
    return name.split(".")[0]


def sign_wbi(params: dict, img_key: str, sub_key: str) -> dict:
    raw = (_wbi_filename(img_key) + _wbi_filename(sub_key)).ljust(64, "0")
    mixin = "".join(raw[index] for index in WBI_MIXIN_INDEX)[:32]
    signed = {key: "".join(ch for ch in str(value) if ch not in "!'()*") for key, value in params.items()}
    signed["wts"] = str(int(time.time()))
    query = urlencode(sorted(signed.items()))
    signed["w_rid"] = hashlib.md5((query + mixin).encode("utf-8")).hexdigest()
    return signed


def _wbi_keys(client: httpx.Client) -> tuple[str, str] | None:
    try:
        response = client.get(NAV_API)
        payload = response.json() if response.content else {}
        data = payload.get("data") if isinstance(payload, dict) else {}
        wbi = (data or {}).get("wbi_img") or {}
        img_key = _wbi_filename(str(wbi.get("img_url") or ""))
        sub_key = _wbi_filename(str(wbi.get("sub_url") or ""))
        if img_key and sub_key:
            return img_key, sub_key
    except Exception:
        return None
    return None


class BilibiliAdapter(SiteAdapter):
    name = "bilibili"

    def can_handle(self, url: str) -> bool:
        host = (urlparse(url).hostname or "").lower()
        return any(host == item or host.endswith("." + item) for item in BILI_HOSTS)

    def resolve(self, url: str, auth: RequestAuth, media_url_override: str = "") -> ResolvedMedia:
        headers = http_headers(auth)
        headers.setdefault("Referer", "https://www.bilibili.com")
        headers.setdefault("Origin", "https://www.bilibili.com")
        extra: dict = {"page_url": url}

        if media_url_override.strip():
            override = media_url_override.strip()
            return ResolvedMedia(
                adapter=self.name,
                source_type=classify_direct_url(override),
                title="B站视频",
                media_url=override,
                page_url=url,
                headers=headers,
                extra=extra,
            )

        try:
            with http_client(follow_redirects=True, headers=headers) as client:
                canonical = self._canonical_url(client, url)
                extra["canonical_url"] = canonical
                bvid, aid, page = parse_bilibili_ref(canonical)
                extra.update({"bvid": bvid, "aid": aid, "page": page})
                if not bvid and not aid:
                    return ResolvedMedia(
                        adapter=self.name,
                        source_type="page",
                        title="B站视频",
                        page_url=url,
                        needs_media_url=True,
                        message="无法从地址识别 BV 号，请使用完整视频链接，或填写媒体地址覆盖。",
                        headers=headers,
                        extra=extra,
                    )
                return self._resolve_official(url, bvid, aid, page, headers, extra, client)
        except httpx.HTTPError as exc:
            return ResolvedMedia(
                adapter=self.name,
                source_type="page",
                title="B站视频",
                page_url=url,
                needs_media_url=True,
                message=f"B站请求失败：{exc}",
                headers=headers,
                extra=extra,
            )

    def _canonical_url(self, client: httpx.Client, url: str) -> str:
        host = (urlparse(url).hostname or "").lower()
        if "bilibili.com" in host and BVID_RE.search(url):
            return url
        response = client.get(url)
        return str(response.url) or url

    def _resolve_official(
        self,
        url: str,
        bvid: str,
        aid: str,
        page: int,
        headers: dict[str, str],
        extra: dict,
        client: httpx.Client,
    ) -> ResolvedMedia:
        params = {"bvid": bvid} if bvid else {"aid": aid}
        view_resp = client.get(VIEW_API, params=params)
        view_resp.raise_for_status()
        view_payload = view_resp.json()
        if view_payload.get("code") != 0:
            message = str(view_payload.get("message") or "稿件不可用")
            return ResolvedMedia(
                adapter=self.name,
                source_type="page",
                title="B站视频",
                page_url=url,
                needs_media_url=True,
                message=f"B站接口返回：{message}。若是登录可见稿件，请配置 B 站 Cookie。",
                headers=headers,
                extra=extra,
            )
        data = view_payload.get("data") or {}
        title = str(data.get("title") or "B站视频")
        author = normalize_author((data.get("owner") or {}).get("name"))
        extra["author"] = author
        extra["owner_mid"] = (data.get("owner") or {}).get("mid")
        pages = data.get("pages") or []
        extra["pages"] = len(pages)
        extra["duration"] = data.get("duration")
        created_at = pick_source_datetime(data)
        extra["pubdate"] = data.get("pubdate")
        extra["ctime"] = data.get("ctime")
        cid = self._cid_for_page(data, pages, page)
        extra["cid"] = cid
        if not cid:
            return ResolvedMedia(
                adapter=self.name,
                source_type="page",
                title=title,
                author=author,
                page_url=url,
                needs_media_url=True,
                message="已找到稿件，但没有可用分 P。请核对 p 参数，或填写媒体地址覆盖。",
                headers=headers,
                created_at=created_at,
                extra=extra,
            )

        play_params = {
            "cid": cid,
            "qn": 16,
            "fnval": 16,
            "fourk": 1,
        }
        if bvid:
            play_params["bvid"] = bvid
        else:
            play_params["avid"] = aid
        play_payload = self._play_payload(client, play_params)
        extra["play_code"] = play_payload.get("code")
        if play_payload.get("code") != 0:
            message = str(play_payload.get("message") or "无法获取播放地址")
            hint = "公开视频一般无需登录；若稿件需登录或大会员，请把 SESSDATA 等 Cookie 粘到 B 站登录档案。"
            return ResolvedMedia(
                adapter=self.name,
                source_type="page",
                title=title,
                author=author,
                page_url=url,
                needs_media_url=True,
                message=f"B站取流失败：{message}。{hint}",
                headers=headers,
                created_at=created_at,
                extra=extra,
            )
        media_url = self._pick_media(play_payload.get("data") or {})
        if not media_url:
            return ResolvedMedia(
                adapter=self.name,
                source_type="page",
                title=title,
                author=author,
                page_url=url,
                needs_media_url=True,
                message="已登录或已拿到稿件信息，但没有可抽音的音轨。请填写媒体地址覆盖。",
                headers=headers,
                created_at=created_at,
                extra=extra,
            )
        extra["media_kind"] = "dash_audio" if "m4s" in media_url or "mcdn" in media_url else "durl"
        play_video = self._pick_video(play_payload.get("data") or {})
        extra["play_audio_url"] = media_url
        extra["play_video_url"] = play_video or media_url
        return ResolvedMedia(
            adapter=self.name,
            source_type="http_audio",
            title=title,
            author=author,
            media_url=media_url,
            page_url=url,
            headers=headers,
            created_at=created_at,
            extra=extra,
        )

    def _play_payload(self, client: httpx.Client, params: dict) -> dict:
        last: dict = {}
        for api in (PLAY_API, PLAY_WBI_API):
            response = client.get(api, params=params)
            response.raise_for_status()
            last = response.json()
            if last.get("code") == 0:
                return last
        return last

    def _cid_for_page(self, data: dict, pages: list, page: int) -> int | str:
        if pages:
            index = min(max(page, 1), len(pages)) - 1
            cid = (pages[index] or {}).get("cid")
            if cid:
                return cid
        return data.get("cid") or ""

    def _pick_media(self, play: dict) -> str:
        dash = play.get("dash") or {}
        audio_items = list(dash.get("audio") or [])
        aac = [item for item in audio_items if "mp4a" in str(item.get("codecs") or "")]
        pool = aac or audio_items
        if pool:
            best = max(pool, key=lambda item: int(item.get("bandwidth") or 0))
            url = str(best.get("baseUrl") or best.get("base_url") or "").strip()
            if url:
                return _https(url)
        durl = play.get("durl") or []
        if durl:
            url = str((durl[0] or {}).get("url") or "").strip()
            if url:
                return _https(url)
        return ""

    def _pick_video(self, play: dict) -> str:
        """优先 AVC 且不超过 720p，便于浏览器回放，避免 4K 转封装过慢。"""
        dash = play.get("dash") or {}
        items = [item for item in (dash.get("video") or []) if isinstance(item, dict)]
        if not items:
            return ""

        def quality(item: dict) -> int:
            try:
                return int(item.get("id") or 0)
            except (TypeError, ValueError):
                return 0

        def bandwidth(item: dict) -> int:
            try:
                return int(item.get("bandwidth") or 0)
            except (TypeError, ValueError):
                return 0

        capped = [item for item in items if quality(item) <= 64] or items
        avc = [item for item in capped if "avc" in str(item.get("codecs") or "").lower()]
        pool = avc or capped
        best = max(pool, key=lambda item: (quality(item), bandwidth(item)))
        url = str(best.get("baseUrl") or best.get("base_url") or "").strip()
        return _https(url) if url else ""

    def list_catalog(
        self,
        auth: RequestAuth,
        catalog_id: str,
        since: datetime | None = None,
    ) -> list[CatalogItem]:
        from app.services.sourcetime import ensure_utc

        mid = parse_bilibili_mid(catalog_id)
        if not mid:
            raise CatalogError("请填写 B 站 UP 的 mid，或空间页地址")
        headers = http_headers(auth)
        headers.setdefault("Referer", "https://www.bilibili.com")
        headers.setdefault("Origin", "https://www.bilibili.com")
        items: list[CatalogItem] = []
        try:
            with http_client(follow_redirects=True, headers=headers) as client:
                wbi_keys = _wbi_keys(client)
                for page in range(1, MAX_SPACE_PAGES + 1):
                    if page > 1 and PAGE_PAUSE:
                        time.sleep(PAGE_PAUSE)
                    payload, limited = _fetch_space_page(client, mid, page, wbi_keys)
                    if limited:
                        if items:
                            break
                        raise CatalogError("稿件列表被限流，请等几分钟再试")
                    if payload.get("code") != 0:
                        raise CatalogError(str(payload.get("message") or "B站稿件列表接口失败"))
                    data = payload.get("data") or {}
                    listing = data.get("list") or {}
                    rows = listing.get("vlist") if isinstance(listing, dict) else listing
                    if not rows:
                        break
                    reached_since = False
                    for row in rows:
                        if not isinstance(row, dict):
                            continue
                        bvid = str(row.get("bvid") or "").strip()
                        if not bvid:
                            continue
                        created_at = pick_source_datetime(row.get("created"), row.get("pubdate"), row)
                        if since is not None and created_at is not None and ensure_utc(created_at) < ensure_utc(since):
                            reached_since = True
                            continue
                        items.append(
                            CatalogItem(
                                source_url=f"https://www.bilibili.com/video/{bvid}",
                                title=str(row.get("title") or "B站视频"),
                                author=normalize_author(row.get("author")),
                                created_at=created_at,
                                extra={"bvid": bvid, "mid": mid, "aid": row.get("aid")},
                            )
                        )
                    if len(rows) < 30 or reached_since:
                        break
        except CatalogError:
            raise
        except (httpx.HTTPError, ValueError, KeyError, json.JSONDecodeError) as exc:
            if items:
                return items
            raise CatalogError(f"B站稿件列表请求失败：{exc}") from exc
        return items


def _space_endpoints(mid: str, page: int, wbi_keys: tuple[str, str] | None) -> list[tuple[str, dict]]:
    params = {"mid": mid, "pn": page, "ps": 30, "order": "pubdate"}
    endpoints: list[tuple[str, dict]] = []
    if wbi_keys:
        signed = sign_wbi({**params, "platform": "web"}, wbi_keys[0], wbi_keys[1])
        endpoints.append((SPACE_WBI_API, signed))
    endpoints.append((SPACE_SEARCH_API, params))
    return endpoints


def _read_payload(response: httpx.Response) -> dict:
    try:
        parsed = response.json() if response.content else {}
        if isinstance(parsed, dict):
            return parsed
    except (ValueError, json.JSONDecodeError):
        return {}
    return {}


def _fetch_space_page(
    client: httpx.Client,
    mid: str,
    page: int,
    wbi_keys: tuple[str, str] | None,
) -> tuple[dict, bool]:
    last_payload: dict = {}
    retries = max(1, len(RETRY_BACKOFF) + 1)
    for attempt in range(retries):
        limited = False
        for url, params in _space_endpoints(mid, page, wbi_keys):
            response = client.get(url, params=params)
            payload = _read_payload(response)
            message = str(payload.get("message") or "")
            if is_bili_rate_limited(payload.get("code"), message, response.status_code):
                last_payload = payload or {"message": "请求过于频繁，请稍后再试"}
                limited = True
                break
            if response.status_code >= 400:
                last_payload = payload or {"message": f"HTTP {response.status_code}"}
                continue
            if payload.get("code") == 0:
                return payload, False
            last_payload = payload
        if not limited:
            return last_payload, False
        if attempt < len(RETRY_BACKOFF):
            pause = RETRY_BACKOFF[attempt]
            if pause:
                time.sleep(pause)
            continue
        return last_payload or {"message": "请求过于频繁，请稍后再试"}, True
    return last_payload or {"message": "请求过于频繁，请稍后再试"}, True
