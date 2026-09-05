import re
from urllib.parse import parse_qs, urlparse

import httpx

from app.services.authctx import RequestAuth, http_headers
from app.services.httpclient import http_client
from app.services.ingest.base import ResolvedMedia, SiteAdapter, classify_direct_url
from app.services.sourcetime import pick_source_datetime

BILI_HOSTS = ("bilibili.com", "b23.tv", "bili2233.cn")
VIEW_API = "https://api.bilibili.com/x/web-interface/view"
PLAY_API = "https://api.bilibili.com/x/player/playurl"
PLAY_WBI_API = "https://api.bilibili.com/x/player/wbi/playurl"
BVID_RE = re.compile(r"(BV[0-9A-Za-z]{10})", re.I)
AV_RE = re.compile(r"(?:/video/)?av(\d+)", re.I)


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


def _https(url: str) -> str:
    if url.startswith("http://"):
        return "https://" + url[7:]
    return url


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
