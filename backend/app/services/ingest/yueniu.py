import base64
import json
from urllib.parse import parse_qs, urlparse

import httpx

from app.services.authctx import RequestAuth, http_headers
from app.services.httpclient import http_client
from app.services.ingest.base import ResolvedMedia, SiteAdapter, classify_direct_url
from app.services.ingest.pageparse import extract_media_urls, extract_title
from app.services.sourcetime import pick_source_datetime

YUENIU_HOSTS = ("yueniuzq.com", "yueniusz.com")
LIVE_API = "https://jflive.yueniuzq.com"
SITE_API = "https://jf.yueniuzq.com"


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
                extra.update(
                    {
                        "live_status": result.get("liveStatus"),
                        "vip_status": result.get("vipStatus"),
                        "author_id": result.get("authorId"),
                    }
                )
                play_items = result.get("videoPlayUrl") or []
                if not play_items:
                    return ResolvedMedia(
                        adapter=self.name,
                        source_type="live",
                        title=title,
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
