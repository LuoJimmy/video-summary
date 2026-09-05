import base64
import json
import re
from urllib.parse import parse_qs, urlparse

import httpx

from app.services.authctx import RequestAuth, http_headers
from app.services.httpclient import http_client
from app.services.ingest.base import ResolvedMedia, SiteAdapter, classify_direct_url
from app.services.ingest.pageparse import extract_media_urls, extract_title
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
                extra.update(
                    {
                        "alive_state": alive.get("alive_state"),
                        "product_name": alive.get("product_name"),
                        "available": available.get("available"),
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
