from datetime import datetime, timezone

import respx
from httpx import Response
from zoneinfo import ZoneInfo

from app.services.authctx import RequestAuth
from app.services.ingest.bilibili import BilibiliAdapter, parse_bilibili_ref
from app.services.ingest.generic import GenericAdapter
from app.services.ingest.registry import pick_adapter, resolve_media
from app.services.ingest.xiaoe import XiaoeAdapter, parse_xiaoe_ref
from app.services.ingest.yueniu import YueniuAdapter


def test_pick_adapter_for_sample_urls():
    assert pick_adapter("https://etrsz.xetslk.com/sl/q1M06").name == "xiaoe"
    assert pick_adapter("https://jf.yueniuzq.com/living/?id=3f14baab82b61eaf6d47deab521b6f7e").name == "yueniu"
    assert pick_adapter("https://www.bilibili.com/video/BV1a4awzsENn").name == "bilibili"
    assert pick_adapter("https://b23.tv/abcd123").name == "bilibili"
    assert pick_adapter("https://cdn.example.com/a.m3u8").name == "generic"


def test_generic_local_and_hls(tmp_path):
    media = tmp_path / "talk.mp4"
    media.write_bytes(b"fake")
    adapter = GenericAdapter()
    local = adapter.resolve(str(media), RequestAuth())
    assert local.source_type == "local_file"
    assert local.media_url == str(media.resolve())
    assert local.created_at is not None

    hls = adapter.resolve("https://cdn.example.com/live/index.m3u8", RequestAuth())
    assert hls.source_type == "hls"
    assert hls.needs_media_url is False


@respx.mock
def test_xiaoe_extracts_m3u8_from_page():
    respx.get("https://etrsz.xetslk.com/sl/q1M06").mock(
        return_value=Response(
            200,
            text='<html><title>课程直播</title><script>var u="https://v-vod.xiaoeknow.com/play.m3u8?token=1";</script></html>',
        )
    )
    resolved = XiaoeAdapter().resolve("https://etrsz.xetslk.com/sl/q1M06", RequestAuth(cookie="sid=1"))
    assert resolved.media_url.startswith("https://v-vod.xiaoeknow.com/play.m3u8")
    assert resolved.title == "课程直播"
    assert resolved.needs_media_url is False


def test_parse_xiaoe_ref_from_short_and_h5():
    app_id, resource_id = parse_xiaoe_ref(
        "https://appdemo.h5.xiaoeknow.com/_alive/api/to_elive?app_id=appdemo&resource_id=l_abc"
    )
    assert app_id == "appdemo"
    assert resource_id == "l_abc"
    app_id, resource_id = parse_xiaoe_ref(
        "https://appdemo.h5.xiaoeknow.com/v4/course/alive/l_abc?app_id=appdemo"
    )
    assert app_id == "appdemo"
    assert resource_id == "l_abc"


@respx.mock
def test_xiaoe_official_lookback_to_m3u8():
    page = "https://appdemo.h5.xiaoeknow.com/v4/course/alive/l_abc?app_id=appdemo"
    respx.get("https://appdemo.h5.xiaoeknow.com/_alive/v2/base_info").mock(
        return_value=Response(
            200,
            json={
                "code": 0,
                "msg": "OK",
                "data": {
                    "alive_info": {
                        "title": "8.13行情梳理",
                        "alive_state": 3,
                        "product_name": "专栏",
                        "zb_start_at": "2026-08-13 20:00:00",
                    },
                    "alive_play": {"alive_video_url": "http://liveplay.example.com/dead.m3u8"},
                    "available_info": {"available": True},
                },
            },
        )
    )
    respx.get("https://appdemo.h5.xiaoeknow.com/_alive/v2/get_lookback_url").mock(
        return_value=Response(
            200,
            json={
                "code": 0,
                "msg": "OK",
                "data": {
                    "aliveVideoUrl": "https://encrypt-k-vod.xet.tech/demo/playlist_eof.m3u8?sign=1",
                    "videoUrlValid": "1",
                },
            },
        )
    )
    resolved = XiaoeAdapter().resolve(page, RequestAuth(cookie="ko_token=demo"))
    assert resolved.needs_media_url is False
    assert resolved.title == "8.13行情梳理"
    assert resolved.created_at is not None
    assert resolved.created_at.astimezone(ZoneInfo("Asia/Shanghai")).day == 13
    assert resolved.media_url.startswith("https://encrypt-k-vod.xet.tech/")
    assert resolved.source_type == "hls"


@respx.mock
def test_xiaoe_requires_override_when_no_media():
    respx.get("https://etrsz.xetslk.com/sl/q1M06").mock(
        return_value=Response(200, text="<html><title>小鹅通提供技术支持</title></html>")
    )
    resolved = XiaoeAdapter().resolve("https://etrsz.xetslk.com/sl/q1M06", RequestAuth())
    assert resolved.needs_media_url is True
    assert "Cookie" in resolved.message


@respx.mock
def test_yueniu_reads_room_id_and_override():
    respx.get("https://jf.yueniuzq.com/living/?id=3f14baab82b61eaf6d47deab521b6f7e").mock(
        return_value=Response(200, text="<html><title>加菲财经直播</title></html>")
    )
    page = "https://jf.yueniuzq.com/living/?id=3f14baab82b61eaf6d47deab521b6f7e"
    unresolved = YueniuAdapter().resolve(page, RequestAuth())
    assert unresolved.extra["room_id"] == "3f14baab82b61eaf6d47deab521b6f7e"
    assert unresolved.needs_media_url is True

    resolved = resolve_media(page, RequestAuth(adapter="yueniu"), media_url_override="https://live.example.com/a.m3u8")
    assert resolved.media_url.endswith("a.m3u8")
    assert resolved.source_type == "hls"


@respx.mock
def test_yueniu_official_replay_to_m3u8():
    page = "https://jf.yueniuzq.com/living/?id=3f14baab82b61eaf6d47deab521b6f7e"
    respx.get("https://jf.yueniuzq.com/headGetUserInfo.json").mock(
        return_value=Response(200, json={"muser_webUserId": "119560085"})
    )
    respx.get("https://jflive.yueniuzq.com/api/live/toDetailSimple").mock(
        return_value=Response(
            200,
            json={
                "code": 0,
                "message": "成功",
                "result": {
                    "liveName": "快人一步，布局主流题材",
                    "liveStatus": 3,
                    "vipStatus": True,
                    "authorId": "119311606",
                    "liveStartTime": "2026-08-13 20:00:00",
                    "videoPlayUrl": [{"name": "高清", "type": "HD", "fileId": "5001"}],
                },
            },
        )
    )
    respx.get("https://jf.yueniuzq.com/api/live/playerSign").mock(
        return_value=Response(200, json={"code": 0, "result": {"sign": "aaa.bbb.ccc"}})
    )
    respx.get("https://playvideo.qcloud.com/getplayinfo/v4/1500034639/5001").mock(
        return_value=Response(
            200,
            json={"media": {"basicInfo": {"duration": 120}, "originalInfo": {"url": "https://jfvod.example.com/a.m3u8"}}},
        )
    )
    resolved = YueniuAdapter().resolve(page, RequestAuth(cookie="_xx_ppt_token=abc; SESSION=def"))
    assert resolved.needs_media_url is False
    assert resolved.title == "快人一步，布局主流题材"
    assert resolved.created_at is not None
    assert resolved.created_at.astimezone(ZoneInfo("Asia/Shanghai")).hour == 20
    assert resolved.media_url.endswith("a.m3u8")


@respx.mock
def test_yueniu_reports_api_error_when_room_missing():
    page = "https://jf.yueniuzq.com/living/?id=de558de121c4fb5a1dca352c5a78a5d"
    respx.get("https://jf.yueniuzq.com/headGetUserInfo.json").mock(
        return_value=Response(200, json={"muser_webUserId": "119560085"})
    )
    respx.get("https://jflive.yueniuzq.com/api/live/toDetailSimple").mock(
        return_value=Response(200, json={"code": 1005001, "message": "直播间不存在或已下架"})
    )
    respx.get(page).mock(return_value=Response(200, text="<html><title>加菲财经直播</title></html>"))
    resolved = YueniuAdapter().resolve(page, RequestAuth(cookie="_xx_ppt_token=abc; SESSION=def"))
    assert resolved.needs_media_url is True
    assert "直播间不存在或已下架" in resolved.message
    assert "已使用约牛登录 Cookie" in resolved.message


def test_parse_bilibili_ref():
    bvid, aid, page = parse_bilibili_ref("https://www.bilibili.com/video/BV1a4awzsENn?p=2&spm_id_from=333")
    assert bvid == "BV1a4awzsENn"
    assert page == 2
    bvid, aid, page = parse_bilibili_ref("https://www.bilibili.com/video/av170001")
    assert aid == "170001"
    assert page == 1


@respx.mock
def test_bilibili_resolves_dash_audio():
    page = "https://www.bilibili.com/video/BV1a4awzsENn"
    respx.get("https://api.bilibili.com/x/web-interface/view").mock(
        return_value=Response(
            200,
            json={
                "code": 0,
                "message": "OK",
                "data": {
                    "bvid": "BV1a4awzsENn",
                    "title": "手机炒股核心卖票方法！-学会多赚50%！",
                    "cid": 32110806955,
                    "duration": 613,
                    "pubdate": int(datetime(2026, 8, 13, 4, 0, tzinfo=timezone.utc).timestamp()),
                    "ctime": int(datetime(2026, 8, 13, 3, 0, tzinfo=timezone.utc).timestamp()),
                    "pages": [{"cid": 32110806955, "page": 1, "part": "P1"}],
                },
            },
        )
    )
    respx.get("https://api.bilibili.com/x/player/playurl").mock(
        return_value=Response(
            200,
            json={
                "code": 0,
                "message": "OK",
                "data": {
                    "dash": {
                        "video": [
                            {
                                "id": 80,
                                "bandwidth": 800000,
                                "codecs": "avc1.640032",
                                "baseUrl": "https://upos.example.com/1080.m4s",
                            },
                            {
                                "id": 64,
                                "bandwidth": 400000,
                                "codecs": "avc1.64001F",
                                "baseUrl": "https://upos.example.com/720.m4s",
                            },
                            {
                                "id": 64,
                                "bandwidth": 500000,
                                "codecs": "hev1.1.6.L120.90",
                                "baseUrl": "https://upos.example.com/720-hevc.m4s",
                            },
                        ],
                        "audio": [
                            {
                                "id": 30216,
                                "bandwidth": 67000,
                                "codecs": "mp4a.40.2",
                                "baseUrl": "https://upos.example.com/64k.m4s",
                            },
                            {
                                "id": 30280,
                                "bandwidth": 192000,
                                "codecs": "mp4a.40.2",
                                "baseUrl": "https://upos.example.com/192k.m4s",
                            },
                        ]
                    }
                },
            },
        )
    )
    resolved = BilibiliAdapter().resolve(page, RequestAuth())
    assert resolved.needs_media_url is False
    assert resolved.adapter == "bilibili"
    assert resolved.title.startswith("手机炒股")
    assert resolved.created_at is not None
    assert resolved.created_at.astimezone(ZoneInfo("Asia/Shanghai")).day == 13
    assert resolved.media_url.endswith("192k.m4s")
    assert resolved.source_type == "http_audio"
    assert resolved.extra["play_audio_url"].endswith("192k.m4s")
    assert resolved.extra["play_video_url"].endswith("720.m4s")


@respx.mock
def test_bilibili_short_link_follows_redirect():
    respx.get("https://b23.tv/abcd123").mock(
        return_value=Response(302, headers={"Location": "https://www.bilibili.com/video/BV1a4awzsENn"})
    )
    respx.get("https://www.bilibili.com/video/BV1a4awzsENn").mock(return_value=Response(200, text="ok"))
    respx.get("https://api.bilibili.com/x/web-interface/view").mock(
        return_value=Response(
            200,
            json={
                "code": 0,
                "data": {
                    "title": "短链视频",
                    "cid": 1,
                    "pages": [{"cid": 1, "page": 1}],
                },
            },
        )
    )
    respx.get("https://api.bilibili.com/x/player/playurl").mock(
        return_value=Response(
            200,
            json={"code": 0, "data": {"durl": [{"url": "https://upos.example.com/a.flv"}]}},
        )
    )
    resolved = BilibiliAdapter().resolve("https://b23.tv/abcd123", RequestAuth())
    assert resolved.needs_media_url is False
    assert resolved.title == "短链视频"
    assert resolved.media_url.endswith("a.flv")
