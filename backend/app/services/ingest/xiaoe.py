import base64
import json
import re
import time
from datetime import datetime
from urllib.parse import parse_qs, urlparse

import httpx

from app.services.authctx import RequestAuth, http_headers
from app.services.httpclient import http_client
from app.services.ingest.base import (
    CatalogError,
    CatalogItem,
    CatalogPage,
    CatalogRef,
    ResolvedMedia,
    SiteAdapter,
    classify_direct_url,
    decode_catalog_cursor,
    encode_catalog_cursor,
)
from app.services.ingest.pageparse import extract_media_urls, extract_title
from app.services.sourceauthor import normalize_author
from app.services.sourcetime import pick_source_datetime

XIAOE_HOSTS = (
    "xetslk.com",
    "xiaoeknow.com",
    "xiaoe-tech.com",
    "xet.tech",
    "xed.plus",
    "xiaoet.cn",
)
ALIVE_PATH_RE = re.compile(r"/course/alive/(l_[A-Za-z0-9]+)", re.I)
XIAOE_SHORT_HOSTS = ("xetslk.com",)
XIAOE_SHORT_PATH_RE = re.compile(r"^/sl/[A-Za-z0-9_\-]+", re.I)


def parse_xiaoe_ref(url: str) -> tuple[str, str]:
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    app_id = (query.get("app_id") or [""])[0].strip()
    resource_id = ((query.get("resource_id") or query.get("alive_id") or [""])[0]).strip()
    match = ALIVE_PATH_RE.search(parsed.path)
    if match and not resource_id:
        resource_id = match.group(1)
    host = (parsed.hostname or "").lower()
    if not app_id and host:
        prefix = host.split(".")[0]
        if prefix.startswith("app") and (
            host.endswith(".h5.xiaoeknow.com")
            or host.endswith(".mp.xiaoeknow.com")
            or host.endswith(".h5.xiaoe-tech.com")
        ):
            app_id = prefix
    params = (query.get("params") or [""])[0]
    if params:
        try:
            padded = params + "=" * (-len(params) % 4)
            payload = json.loads(base64.b64decode(padded))
            app_id = app_id or str(payload.get("app_id") or "").strip()
            resource_id = resource_id or str(payload.get("resource_id") or "").strip()
        except Exception:
            pass
    return app_id, resource_id


def detect_xiaoe_catalog(url: str) -> CatalogRef | None:
    text = (url or "").strip()
    if not text:
        return None
    candidate = text
    if "://" not in text and "." in text:
        candidate = "https://" + text
    if "://" in candidate or "." in candidate:
        app_id, resource_id = parse_xiaoe_ref(candidate)
    else:
        app_id, resource_id = parse_xiaoe_catalog_id(text), ""
    if app_id and not resource_id:
        return CatalogRef("xiaoe", app_id, "小鹅通店铺")
    return None


def parse_xiaoe_catalog_id(catalog_id: str) -> str:
    text = (catalog_id or "").strip()
    if re.fullmatch(r"app[A-Za-z0-9]+", text, re.I):
        return text
    if text and "://" not in text and "." not in text:
        if text.lower().startswith("app"):
            return text
    candidate = text
    if text and "://" not in text and "." in text:
        candidate = "https://" + text
    app_id, _ = parse_xiaoe_ref(candidate)
    return app_id


def is_xiaoe_short_link(url: str) -> bool:
    text = (url or "").strip()
    if not text:
        return False
    parsed = urlparse(text if "://" in text else "https://" + text)
    host = (parsed.hostname or "").lower()
    if not any(host == item or host.endswith("." + item) for item in XIAOE_SHORT_HOSTS):
        return False
    return bool(XIAOE_SHORT_PATH_RE.match(parsed.path or ""))


def expand_xiaoe_short_link(url: str, auth: RequestAuth) -> str:
    """跟随 /sl/ 分享短链；落地址里才带 app_id / resource_id，可据此区分店铺与单条内容。"""
    text = (url or "").strip()
    if not is_xiaoe_short_link(text):
        return text
    headers = http_headers(auth)
    headers.setdefault("Referer", text)
    try:
        with http_client(follow_redirects=True, headers=headers) as client:
            response = client.get(text)
    except httpx.HTTPError:
        return text
    final = str(response.url or "").strip()
    return final or text


XIAOE_LOGIN_HINT = (
    "小鹅通需要登录。请在浏览器打开该店铺并登录后，把 Cookie 粘到「站点 → 小鹅通登录档案」。"
)


def _xiaoe_payload_message(payload: dict) -> str:
    return str(payload.get("msg") or payload.get("message") or "").strip()


def _xiaoe_login_required(payload: dict) -> bool:
    code = payload.get("code")
    text = _xiaoe_payload_message(payload).lower()
    return code in {11301, 11302} or "login" in text or "auth" in text


def _xiaoe_api_error(payload: dict, fallback: str) -> str:
    if _xiaoe_login_required(payload):
        return XIAOE_LOGIN_HINT
    return _xiaoe_payload_message(payload) or fallback


def _xiaoe_shop_origin(app_id: str) -> str:
    return f"https://{app_id}.h5.xiaoeknow.com"


def _xiaoe_request_json(
    client: httpx.Client,
    method: str,
    url: str,
    **kwargs,
) -> dict | None:
    last_error: Exception | None = None
    for attempt in range(4):
        try:
            response = client.request(method, url, **kwargs)
        except httpx.HTTPError as exc:
            last_error = exc
            time.sleep(0.3 * (attempt + 1))
            continue
        if not response.content:
            time.sleep(0.3 * (attempt + 1))
            continue
        try:
            payload = response.json()
        except json.JSONDecodeError:
            if response.status_code >= 400:
                return None
            time.sleep(0.3 * (attempt + 1))
            continue
        if isinstance(payload, dict):
            return payload
        return None
    if last_error is not None:
        raise last_error
    return None


def _xiaoe_component_ids(html: str) -> list[int]:
    found: list[int] = []
    seen: set[int] = set()
    for blob in re.findall(r"eyJ[A-Za-z0-9_\-]{12,}", html or ""):
        padded = blob + "=" * (-len(blob) % 4)
        try:
            payload = json.loads(base64.urlsafe_b64decode(padded))
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        raw = payload.get("component_id")
        try:
            component_id = int(raw)
        except (TypeError, ValueError):
            continue
        if component_id > 0 and component_id not in seen:
            seen.add(component_id)
            found.append(component_id)
    for match in re.findall(r'(\d{6,}),\s*"搜索"', html or ""):
        component_id = int(match)
        if component_id not in seen:
            seen.add(component_id)
            found.append(component_id)
    return found


def _xiaoe_micro_page_id(html: str, app_id: str) -> str:
    match = re.search(rf'"{re.escape(app_id)}","(\d+)"', html or "")
    return match.group(1) if match else ""


def _xiaoe_shop_item(app_id: str, shop: str, row: dict) -> CatalogItem | None:
    resource_id = str(
        row.get("spu_id") or row.get("alive_id") or row.get("src_id") or ""
    ).strip()
    if not resource_id:
        return None
    src_type = str(row.get("src_type") or row.get("info_tag") or "").lower()
    type_flag = row.get("type")
    jump = str(row.get("jump_url") or "")
    is_alive = (
        resource_id.startswith("l_")
        or src_type == "alive"
        or type_flag in (4, "4")
        or "/course/alive/" in jump
    )
    if not is_alive:
        return None
    return CatalogItem(
        source_url=f"{shop}/v4/course/alive/{resource_id}?app_id={app_id}",
        title=str(row.get("title") or "小鹅通直播"),
        author=normalize_author(row.get("product_name")),
        created_at=pick_source_datetime(
            row.get("lesson_start_at"),
            row.get("zb_start_at"),
            row.get("alive_start_at"),
            row,
        ),
        extra={"app_id": app_id, "resource_id": resource_id, "src_type": src_type},
    )


def _https(url: str) -> str:
    if url.startswith("http://"):
        return "https://" + url[7:]
    return url


def _first_http(*candidates: object) -> str:
    for item in candidates:
        text = str(item or "").strip()
        if text.startswith("http"):
            return _https(text)
    return ""


class XiaoeAdapter(SiteAdapter):
    name = "xiaoe"

    def can_handle(self, url: str) -> bool:
        host = (urlparse(url).hostname or "").lower()
        return any(host == item or host.endswith("." + item) for item in XIAOE_HOSTS)

    def resolve(self, url: str, auth: RequestAuth, media_url_override: str = "") -> ResolvedMedia:
        headers = http_headers(auth)
        headers.setdefault("Referer", url)
        if media_url_override.strip():
            override = media_url_override.strip()
            return ResolvedMedia(
                adapter=self.name,
                source_type=classify_direct_url(override),
                title="",
                media_url=override,
                page_url=url,
                headers=headers,
                extra={"short_url": url},
            )

        app_id, resource_id = parse_xiaoe_ref(url)
        page_url = url
        body = ""
        title = ""
        if not (app_id and resource_id):
            try:
                with http_client(follow_redirects=True, headers=headers) as client:
                    response = client.get(url)
                    page_url = str(response.url)
                    body = response.text[:400_000]
                    title = extract_title(body)
                    seen = [url, page_url, *[str(item.url) for item in response.history]]
                    location = response.headers.get("location") or ""
                    if location:
                        seen.append(location)
                    for item in seen:
                        found_app, found_res = parse_xiaoe_ref(item)
                        app_id = app_id or found_app
                        resource_id = resource_id or found_res
                        if app_id and resource_id:
                            break
            except httpx.HTTPError as exc:
                return ResolvedMedia(
                    adapter=self.name,
                    source_type="page",
                    page_url=url,
                    needs_media_url=True,
                    message=f"小鹅通页面请求失败：{exc}",
                    headers=headers,
                )

        extra = {"short_url": url, "app_id": app_id, "resource_id": resource_id, "final_url": page_url}
        if app_id and resource_id:
            official = self._resolve_official(url, app_id, resource_id, auth, headers, extra)
            if official is not None:
                if not official.title:
                    official.title = title or "小鹅通内容"
                return official

        media_urls = extract_media_urls(body)
        if media_urls:
            media = media_urls[0]
            return ResolvedMedia(
                adapter=self.name,
                source_type=classify_direct_url(media),
                title=title or "小鹅通内容",
                media_url=media,
                page_url=page_url,
                headers=headers,
                extra=extra,
            )

        hint = (
            "已跟随短链，但官方接口未返回可转写的播放地址。"
            "请确认登录档案 Cookie 有效，或从浏览器 Network 复制 m3u8/mp4 填入媒体地址覆盖。"
        )
        if not auth.cookie:
            hint = "未配置小鹅通登录 Cookie。该短链通常需要登录后才能取流。"
        return ResolvedMedia(
            adapter=self.name,
            source_type="page",
            title=title or "小鹅通内容",
            page_url=page_url,
            needs_media_url=True,
            message=hint,
            headers=headers,
            extra=extra,
        )

    def _resolve_official(
        self,
        url: str,
        app_id: str,
        resource_id: str,
        auth: RequestAuth,
        headers: dict[str, str],
        extra: dict,
    ) -> ResolvedMedia | None:
        shop = f"https://{app_id}.h5.xiaoeknow.com"
        api_headers = {
            **headers,
            "Referer": f"{shop}/",
            "app_id": app_id,
            "AppId": app_id,
            "kpi_client": "9",
            "Accept": "application/json",
        }
        try:
            with http_client(follow_redirects=True, headers=api_headers) as client:
                info_resp = client.get(
                    f"{shop}/_alive/v2/base_info",
                    params={"resource_id": resource_id, "type": 12, "app_id": app_id},
                )
                info_resp.raise_for_status()
                info_payload = info_resp.json()
                if info_payload.get("code") != 0:
                    extra["base_info_message"] = str(info_payload.get("msg") or "")
                    return None
                data = info_payload.get("data") or {}
                alive = data.get("alive_info") or {}
                play = data.get("alive_play") or {}
                available = data.get("available_info") or {}
                title = str(alive.get("title") or "小鹅通直播")
                created_at = pick_source_datetime(alive)
                author = normalize_author((data.get("alive_conf") or {}).get("wx_app_name"))
                extra.update(
                    {
                        "alive_state": alive.get("alive_state"),
                        "product_name": alive.get("product_name"),
                        "available": available.get("available"),
                        "author": author,
                    }
                )
                lookback: dict = {}
                look_resp = client.get(
                    f"{shop}/_alive/v2/get_lookback_url",
                    params={"alive_id": resource_id, "app_id": app_id},
                )
                if look_resp.status_code == 200:
                    look_payload = look_resp.json()
                    if look_payload.get("code") == 0:
                        lookback = look_payload.get("data") or {}
                    else:
                        extra["lookback_message"] = str(look_payload.get("msg") or "")
                media_url = self._pick_media(lookback, play, alive.get("alive_state"))
                if not media_url:
                    return ResolvedMedia(
                        adapter=self.name,
                        source_type="live",
                        title=title,
                        author=author,
                        page_url=url,
                        needs_media_url=True,
                        message="已登录并解析到直播信息，但当前没有可转写的回放或直播地址。请填写媒体地址覆盖。",
                        headers=headers,
                        created_at=created_at,
                        extra=extra,
                    )
                extra["lookback"] = bool(lookback.get("aliveVideoUrl") or lookback.get("miniAliveVideoUrl"))
                return ResolvedMedia(
                    adapter=self.name,
                    source_type=classify_direct_url(media_url),
                    title=title,
                    author=author,
                    media_url=media_url,
                    page_url=url,
                    headers=headers,
                    created_at=created_at,
                    extra=extra,
                )
        except (httpx.HTTPError, ValueError, KeyError, json.JSONDecodeError) as exc:
            extra["official_error"] = str(exc)
            return None

    def _pick_media(self, lookback: dict, play: dict, alive_state: object) -> str:
        valid = lookback.get("videoUrlValid")
        if valid in (None, "", "1", 1, True):
            replay = _first_http(
                lookback.get("aliveVideoUrl"),
                lookback.get("miniAliveVideoUrl"),
                lookback.get("aliveVideoMp4Url"),
            )
            if replay:
                return replay
        if str(alive_state) == "1":
            live = _first_http(
                play.get("alive_video_url"),
                play.get("mini_alive_video_url"),
                play.get("pc_alive_video_url"),
            )
            if live:
                return live
        return _first_http(
            play.get("alive_video_url"),
            play.get("mini_alive_video_url"),
            play.get("pc_alive_video_url"),
        )

    def _list_shop_more(
        self,
        client: httpx.Client,
        app_id: str,
        shop: str,
        since: datetime | None,
        limit: int | None,
    ) -> CatalogPage | None:
        from app.services.sourcetime import ensure_utc

        try:
            home = client.get(f"{shop}/p/decorate/homepage")
        except httpx.HTTPError:
            return None
        html = home.text if home.status_code == 200 else ""
        if not html:
            return None
        component_ids = _xiaoe_component_ids(html)
        micro_page_id = _xiaoe_micro_page_id(html, app_id)
        if not component_ids:
            return None
        body = {
            "app_id": app_id,
            "micro_page_id": micro_page_id,
            "user_id": "",
            "force_collection": 1,
            "app_version": "0.1",
            "buz_data": {
                "channel_id": "",
                "micro_page_id": micro_page_id,
                "agent_mark": "h5_core_page",
                "lang": "zh",
            },
            "buz_uri": f"{shop}/p/decorate/homepage",
            "client": 1,
            "from_h5_home": 1,
            "page_index": 1,
            "page_size": 50,
        }
        rows: list[dict] = []
        for component_id in component_ids:
            payload = _xiaoe_request_json(
                client,
                "POST",
                f"{shop}/xe.micro_page.h5_more/1.0.0",
                json={**body, "component_id": component_id},
            )
            if not payload or payload.get("code") != 0:
                continue
            data = payload.get("data") or {}
            component = data.get("component") or {}
            found = component.get("list") or data.get("list") or []
            if isinstance(found, list) and found:
                rows = [row for row in found if isinstance(row, dict)]
                break
        if not rows:
            return None
        items: list[CatalogItem] = []
        for row in rows:
            item = _xiaoe_shop_item(app_id, shop, row)
            if item is None:
                continue
            if since is not None and item.created_at is not None and ensure_utc(item.created_at) < ensure_utc(since):
                continue
            items.append(item)
            if limit is not None and len(items) >= limit:
                break
        if not items:
            return None
        return CatalogPage(items=items)

    def list_catalog(
        self,
        auth: RequestAuth,
        catalog_id: str,
        since: datetime | None = None,
        cursor: str | None = None,
        limit: int | None = None,
    ) -> CatalogPage:
        from app.services.sourcetime import ensure_utc

        app_id = parse_xiaoe_catalog_id(catalog_id)
        if not app_id:
            raise CatalogError("请填写小鹅通店铺 app_id，或粘贴店铺 H5 / 小程序店铺地址")
        headers = http_headers(auth)
        shop = _xiaoe_shop_origin(app_id)
        headers.setdefault("Referer", f"{shop}/p/decorate/homepage")
        headers.setdefault("Origin", shop)
        api_headers = {
            **headers,
            "app_id": app_id,
            "AppId": app_id,
            "kpi_client": "9",
            "client": "1",
            "Accept": "application/json, text/html",
        }
        state = decode_catalog_cursor(cursor)
        page = max(1, int(state.get("p") or 1))
        offset = max(0, int(state.get("off") or 0))
        items: list[CatalogItem] = []
        schedule = limit is None
        try:
            with http_client(follow_redirects=True, headers=api_headers) as client:
                if state.get("src") != "alive":
                    shop_headers = {
                        key: value
                        for key, value in api_headers.items()
                        if key.lower() != "cookie"
                    }
                    with http_client(follow_redirects=True, headers=shop_headers) as shop_client:
                        shop_page = self._list_shop_more(shop_client, app_id, shop, since, limit)
                    if shop_page is not None:
                        return shop_page
                pages_fetched = 0
                while True:
                    if schedule and pages_fetched >= 15:
                        break
                    response = client.get(
                        f"{shop}/_alive/v2/list",
                        params={"app_id": app_id, "page": page, "page_size": 20},
                    )
                    if response.status_code >= 400:
                        raise CatalogError("小鹅通直播列表接口失败")
                    try:
                        payload = response.json()
                    except json.JSONDecodeError as exc:
                        raise CatalogError("小鹅通直播列表接口失败") from exc
                    if not isinstance(payload, dict):
                        raise CatalogError("小鹅通直播列表接口失败")
                    if payload.get("code") != 0:
                        raise CatalogError(_xiaoe_api_error(payload, "小鹅通直播列表接口失败"))
                    data = payload.get("data") or {}
                    rows = data.get("list") or []
                    pages_fetched += 1
                    if not rows:
                        return CatalogPage(items=items)
                    converted: list[CatalogItem] = []
                    for row in rows:
                        if not isinstance(row, dict):
                            continue
                        if str(row.get("recycle_bin_state") or "0") not in {"0", ""}:
                            continue
                        state_flag = row.get("alive_state")
                        # 未开始且无回放的场次跳过；0 在 Python 里是假值，不能用 `or`
                        if state_flag in (0, "0"):
                            continue
                        resource_id = str(row.get("id") or row.get("resource_id") or "").strip()
                        if not resource_id:
                            continue
                        created_at = pick_source_datetime(row)
                        if since is not None and created_at is not None and ensure_utc(created_at) < ensure_utc(since):
                            continue
                        author = normalize_author(
                            row.get("wx_app_name")
                            or ((row.get("guest_list") or [{}])[0] or {}).get("user_name")
                        )
                        converted.append(
                            CatalogItem(
                                source_url=f"{shop}/v4/course/alive/{resource_id}?app_id={app_id}",
                                title=str(row.get("title") or "小鹅通直播"),
                                author=author,
                                created_at=created_at,
                                extra={"app_id": app_id, "resource_id": resource_id, "alive_state": row.get("alive_state")},
                            )
                        )
                    usable = converted[offset:] if offset else converted
                    offset = 0
                    if limit is not None:
                        room = max(0, limit - len(items))
                        if len(usable) > room:
                            taken = len(converted) - len(usable) + room
                            items.extend(usable[:room])
                            return CatalogPage(
                                items=items,
                                next_cursor=encode_catalog_cursor({"src": "alive", "p": page, "off": taken}),
                            )
                    items.extend(usable)
                    if len(rows) < 20:
                        return CatalogPage(items=items)
                    page += 1
                    if limit is not None and len(items) >= limit:
                        return CatalogPage(
                            items=items,
                            next_cursor=encode_catalog_cursor({"src": "alive", "p": page, "off": 0}),
                        )
        except CatalogError:
            raise
        except (httpx.HTTPError, ValueError, KeyError, json.JSONDecodeError) as exc:
            raise CatalogError(f"小鹅通直播列表请求失败：{exc}") from exc
        return CatalogPage(items=items)
