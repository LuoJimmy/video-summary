import base64
import json
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

YUENIU_HOSTS = ("yueniuzq.com", "yueniusz.com")
LIVE_API = "https://jflive.yueniuzq.com"
SITE_API = "https://jf.yueniuzq.com"


def detect_yueniu_catalog(url: str) -> CatalogRef | None:
    parsed = urlparse(url or "")
    host = (parsed.hostname or "").lower()
    if not any(host == item or host.endswith("." + item) for item in YUENIU_HOSTS):
        return None
    room_id = (parse_qs(parsed.query).get("id") or [""])[0].strip()
    if room_id:
        return None
    return CatalogRef("yueniu", "", "约牛直播日历")


def cookie_value(cookie: str, name: str) -> str:
    for part in cookie.split(";"):
        item = part.strip()
        if item.startswith(name + "="):
            return item[len(name) + 1 :]
    return ""


def jwt_payload(token: str) -> dict:
    try:
        part = token.split(".")[1]
        part += "=" * (-len(part) % 4)
        return json.loads(base64.urlsafe_b64decode(part))
    except Exception:
        return {}


class YueniuAdapter(SiteAdapter):
    name = "yueniu"

    def can_handle(self, url: str) -> bool:
        host = (urlparse(url).hostname or "").lower()
        return any(host == item or host.endswith("." + item) for item in YUENIU_HOSTS)

    def resolve(self, url: str, auth: RequestAuth, media_url_override: str = "") -> ResolvedMedia:
        headers = http_headers(auth)
        headers.setdefault("Referer", url)
        headers.setdefault("Origin", "https://jf.yueniuzq.com")
        room_id = parse_qs(urlparse(url).query).get("id", [""])[0]
        extra = {"room_id": room_id, "live_api": f"{LIVE_API}/api/live/toDetailSimple"}

        if media_url_override.strip():
            override = media_url_override.strip()
            return ResolvedMedia(
                adapter=self.name,
                source_type=classify_direct_url(override),
                title="加菲财经直播",
                media_url=override,
                page_url=url,
                headers=headers,
                extra=extra,
            )

        if auth.cookie and room_id:
            resolved = self._resolve_official(url, room_id, auth, headers, extra)
            if resolved is not None:
                return resolved

        title = "加菲财经直播"
        body = ""
        try:
            with http_client(follow_redirects=True, headers=headers) as client:
                response = client.get(url)
                body = response.text[:400_000]
                title = extract_title(body) or title
        except httpx.HTTPError as exc:
            return ResolvedMedia(
                adapter=self.name,
                source_type="live",
                title=title,
                page_url=url,
                needs_media_url=True,
                message=f"约牛直播页请求失败：{exc}",
                headers=headers,
                extra=extra,
            )

        media_urls = extract_media_urls(body)
        if media_urls:
            media = media_urls[0]
            return ResolvedMedia(
                adapter=self.name,
                source_type=classify_direct_url(media),
                title=title,
                media_url=media,
                page_url=url,
                headers=headers,
                extra=extra,
            )

        hint = (
            "直播页使用腾讯云播放器，流地址在登录后由 jflive 动态下发。"
            "请配置约牛登录 Cookie，或把浏览器中的 m3u8/flv 填入媒体地址覆盖。"
        )
        if not auth.cookie:
            hint = "未配置约牛登录 Cookie。该直播间在未登录时无法取流。"
        elif extra.get("detail_message"):
            hint = (
                f"已使用约牛登录 Cookie，但接口返回：{extra['detail_message']}。"
                "请核对直播间地址，或把浏览器中的 m3u8/flv 填入媒体地址覆盖。"
            )
        elif extra.get("sign_message"):
            hint = f"已使用约牛登录 Cookie，但取播放签名失败：{extra['sign_message']}。"
        elif extra.get("official_error"):
            hint = f"已使用约牛登录 Cookie，但官方取流失败：{extra['official_error']}。"
        return ResolvedMedia(
            adapter=self.name,
            source_type="live",
            title=title,
            page_url=url,
            needs_media_url=True,
            message=hint,
            headers=headers,
            extra=extra,
        )

    def _resolve_official(
        self,
        url: str,
        room_id: str,
        auth: RequestAuth,
        headers: dict[str, str],
        extra: dict,
    ) -> ResolvedMedia | None:
        token = cookie_value(auth.cookie, "_xx_ppt_token")
        try:
            with http_client(follow_redirects=True, headers=headers) as client:
                user_id = self._user_id(client)
                detail_resp = client.get(
                    f"{LIVE_API}/api/live/toDetailSimple",
                    params={
                        "liveId": room_id,
                        "from": "pc",
                        "token": token,
                        "includeSource": "true",
                    },
                    headers={**headers, "token": token, "uid": user_id},
                )
                detail_resp.raise_for_status()
                payload = detail_resp.json()
                if payload.get("code") != 0:
                    extra["detail_message"] = str(payload.get("message") or "")
                    return None
                result = payload.get("result") or {}
                title = str(result.get("liveName") or "加菲财经直播")
                created_at = pick_source_datetime(result)
                author = normalize_author((result.get("user") or {}).get("name"))
                extra.update(
                    {
                        "live_status": result.get("liveStatus"),
                        "vip_status": result.get("vipStatus"),
                        "author_id": result.get("authorId"),
                        "author": author,
                    }
                )
                play_items = result.get("videoPlayUrl") or []
                if not play_items:
                    return ResolvedMedia(
                        adapter=self.name,
                        source_type="live",
                        title=title,
                        author=author,
                        page_url=url,
                        needs_media_url=True,
                        message="已登录，但当前没有回放点播地址（可能未开播或仅有 WebRTC 直播）。请填写媒体地址覆盖。",
                        headers=headers,
                        created_at=created_at,
                        extra=extra,
                    )
                preferred = next((item for item in play_items if item.get("type") == "HD"), play_items[0])
                file_id = str(preferred.get("fileId") or "")
                video_type = str(preferred.get("type") or "HD")
                sign_resp = client.get(
                    f"{SITE_API}/api/live/playerSign",
                    params={
                        "from": "pc",
                        "fileId": file_id,
                        "videoType": video_type,
                        "authorId": str(result.get("authorId") or ""),
                        "liveId": room_id,
                        "token": token,
                        "uid": user_id,
                    },
                    headers={**headers, "token": token, "uid": user_id},
                )
                sign_resp.raise_for_status()
                sign_payload = sign_resp.json()
                if sign_payload.get("code") != 0:
                    extra["sign_message"] = str(sign_payload.get("message") or "")
                    return None
                psign = str((sign_payload.get("result") or {}).get("sign") or "")
                app_id = str((jwt_payload(psign).get("appId") or "1500034639"))
                play_resp = client.get(
                    f"https://playvideo.qcloud.com/getplayinfo/v4/{app_id}/{file_id}",
                    params={"psign": psign},
                )
                play_resp.raise_for_status()
                play_info = play_resp.json()
                media_url = str(((play_info.get("media") or {}).get("originalInfo") or {}).get("url") or "")
                duration = ((play_info.get("media") or {}).get("basicInfo") or {}).get("duration")
                extra["duration"] = duration
                extra["file_id"] = file_id
                if not media_url:
                    return None
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
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            extra["official_error"] = str(exc)
            return None

    def _user_id(self, client: httpx.Client) -> str:
        response = client.get(f"{SITE_API}/headGetUserInfo.json")
        response.raise_for_status()
        data = response.json()
        return str(data.get("muser_webUserId") or "")

    def _yueniu_logged_in(self, client: httpx.Client) -> bool:
        try:
            payload = client.get(f"{SITE_API}/islogin.json").json()
        except (httpx.HTTPError, ValueError, json.JSONDecodeError):
            return False
        if not isinstance(payload, dict):
            return False
        if payload.get("success") is True:
            return True
        message = str(payload.get("message") or "").lower()
        return message not in {"logout", "未登录", "nologin", ""}

    def _yueniu_api_error(self, payload: dict) -> str:
        code = payload.get("code")
        if code in (0, "0"):
            return ""
        text = str(payload.get("message") or "").strip()
        if str(code) == "1010015" or "登录" in text:
            return "约牛登录已失效，请重新从浏览器复制 Cookie 到「站点 → 约牛登录档案」。"
        return text or "约牛直播列表接口失败"

    def _yueniu_get(self, client: httpx.Client, path: str, headers: dict, **params) -> dict:
        query = {key: value for key, value in params.items() if value not in (None, "")}
        response = client.get(f"{SITE_API}{path}", params=query, headers=headers)
        response.raise_for_status()
        payload = response.json()
        error = self._yueniu_api_error(payload)
        if error:
            raise CatalogError(error)
        result = payload.get("result")
        return result if isinstance(result, dict) else {}

    def _yueniu_live_item(self, row: dict, author: str = "") -> CatalogItem | None:
        live_id = str(row.get("liveId") or row.get("id") or "").strip()
        if not live_id:
            return None
        if row.get("status") in (4, "4"):
            return None
        return CatalogItem(
            source_url=f"https://jf.yueniuzq.com/living/?id={live_id}",
            title=str(row.get("liveName") or row.get("title") or "加菲财经直播"),
            author=normalize_author(
                author
                or row.get("authorName")
                or ((row.get("user") or {}) if isinstance(row.get("user"), dict) else {}).get("name")
            ),
            created_at=pick_source_datetime(
                row.get("startTs"),
                row.get("date"),
                row.get("startTime"),
                row,
            ),
            extra={
                "live_id": live_id,
                "column_id": row.get("columnId"),
                "status": row.get("status"),
            },
        )

    def _yueniu_column_match(self, row: dict, catalog_id: str) -> bool:
        if not catalog_id:
            return True
        return catalog_id in {
            str(row.get("columnId") or "").strip(),
            str(row.get("authorId") or "").strip(),
        }

    def list_catalog(
        self,
        auth: RequestAuth,
        catalog_id: str,
        since: datetime | None = None,
        cursor: str | None = None,
        limit: int | None = None,
    ) -> CatalogPage:
        from app.services.sourcetime import ensure_utc

        if not auth.cookie.strip():
            raise CatalogError("未配置约牛登录 Cookie，无法拉取直播日历")
        headers = http_headers(auth)
        headers.setdefault("Referer", "https://jf.yueniuzq.com/")
        headers.setdefault("Origin", "https://jf.yueniuzq.com")
        token = cookie_value(auth.cookie, "_xx_ppt_token")
        wanted = (catalog_id or "").strip()
        state = decode_catalog_cursor(cursor)
        col_start = str(state.get("cs") or "")
        col_skip = max(0, int(state.get("cskip") or 0))
        column_id = str(state.get("cid") or wanted)
        live_start = str(state.get("ls") or "")
        offset = max(0, int(state.get("off") or 0))
        items: list[CatalogItem] = []
        schedule = limit is None
        requests_made = 0

        def take(converted: list[CatalogItem], page_cursor: dict) -> CatalogPage | None:
            nonlocal offset
            usable = converted[offset:] if offset else converted
            offset = 0
            if limit is None:
                items.extend(usable)
                return None
            room = max(0, limit - len(items))
            if len(usable) > room:
                taken = len(converted) - len(usable) + room
                items.extend(usable[:room])
                page_cursor["off"] = taken
                return CatalogPage(items=items, next_cursor=encode_catalog_cursor(page_cursor))
            items.extend(usable)
            return None

        try:
            with http_client(follow_redirects=True, headers=headers) as client:
                if not self._yueniu_logged_in(client):
                    raise CatalogError(
                        "约牛登录已失效，请重新从浏览器复制 Cookie 到「站点 → 约牛登录档案」。"
                    )
                user_id = self._user_id(client)
                req_headers = {**headers, "token": token, "uid": user_id}
                columns: list[dict] = []
                if not column_id or wanted:
                    while True:
                        if schedule and requests_made >= 20:
                            break
                        result = self._yueniu_get(
                            client,
                            "/api/live/columnList",
                            req_headers,
                            **{"from": "pc", "pageSize": 15, "startTime": col_start},
                        )
                        requests_made += 1
                        rows = [row for row in (result.get("list") or []) if isinstance(row, dict)]
                        next_col = str(result.get("startTime") or "")
                        if not rows and not columns and not user_id:
                            raise CatalogError(
                                "约牛未返回专栏。请确认已登录，并重新把 jf.yueniuzq.com 的 Cookie 粘到登录档案。"
                            )
                        matched = [row for row in rows if self._yueniu_column_match(row, wanted)]
                        columns.extend(matched)
                        if wanted and matched:
                            col_start = next_col
                            break
                        if not next_col or len(rows) < 15:
                            col_start = ""
                            break
                        col_start = next_col
                    if wanted:
                        if columns:
                            column_id = str(columns[0].get("columnId") or wanted)
                            columns = columns[col_skip:]
                        else:
                            column_id = wanted
                            columns = [{"columnId": wanted, "authorName": ""}]
                    else:
                        columns = columns[col_skip:]
                else:
                    columns = [{"columnId": column_id, "authorName": ""}]

                col_index = 0
                while col_index < len(columns):
                    if schedule and requests_made >= 20:
                        break
                    column = columns[col_index]
                    cid = str(column.get("columnId") or "").strip()
                    if not cid:
                        col_index += 1
                        live_start = ""
                        continue
                    author = str(column.get("authorName") or "")
                    result = self._yueniu_get(
                        client,
                        "/api/live/V2/liveList",
                        req_headers,
                        **{
                            "from": "pc",
                            "columnId": cid,
                            "pageSize": 50,
                            "startTime": live_start,
                        },
                    )
                    requests_made += 1
                    rows = [row for row in (result.get("list") or []) if isinstance(row, dict)]
                    next_live = str(result.get("startTime") or "")
                    converted: list[CatalogItem] = []
                    reached_since = False
                    for row in rows:
                        item = self._yueniu_live_item(row, author=author)
                        if item is None:
                            continue
                        if (
                            since is not None
                            and item.created_at is not None
                            and ensure_utc(item.created_at) < ensure_utc(since)
                        ):
                            reached_since = True
                            continue
                        converted.append(item)
                    next_state = {
                        "cs": col_start,
                        "cskip": col_skip + col_index,
                        "cid": cid,
                        "ls": next_live,
                        "off": 0,
                    }
                    filled = take(converted, next_state)
                    if filled is not None:
                        return filled
                    column_done = not next_live or len(rows) < 50 or reached_since
                    if limit is not None and len(items) >= limit:
                        if column_done:
                            next_state = {
                                "cs": col_start,
                                "cskip": col_skip + col_index + 1,
                                "cid": "",
                                "ls": "",
                                "off": 0,
                            }
                        return CatalogPage(
                            items=items,
                            next_cursor=encode_catalog_cursor(next_state),
                        )
                    if column_done:
                        col_index += 1
                        live_start = ""
                        continue
                    live_start = next_live
        except CatalogError:
            raise
        except (httpx.HTTPError, ValueError, KeyError, json.JSONDecodeError) as exc:
            raise CatalogError(f"约牛直播列表请求失败：{exc}") from exc
        return CatalogPage(items=items)
