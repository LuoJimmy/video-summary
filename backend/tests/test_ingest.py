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


def test_generic_reports_local_path_missing_in_container():
    adapter = GenericAdapter()
    plain = adapter.resolve("/vs-no-such-dir/a.mp4", RequestAuth())
    assert plain.needs_media_url is True
    assert "本地任务" in plain.message

    file_url = adapter.resolve("file:///vs-no-such-dir/a.mp4", RequestAuth())
    assert file_url.needs_media_url is True
    assert "本地任务" in file_url.message

    windows = adapter.resolve("D:\\media\\a.mp4", RequestAuth())
    assert windows.needs_media_url is True

    protocol_relative = adapter.resolve("//cdn.example.com/a.mp4", RequestAuth())
    assert protocol_relative.source_type == "http_video"


def test_generic_document_and_web_page(tmp_path):
    from app.services.ingest.base import classify_direct_url, is_document_source

    note = tmp_path / "notes.pdf"
    note.write_bytes(b"%PDF")
    adapter = GenericAdapter()
    local = adapter.resolve(str(note), RequestAuth())
    assert local.source_type == "local_document"
    assert is_document_source(local.source_type)
    assert local.needs_media_url is False

    page = adapter.resolve("https://example.com/article/hello", RequestAuth())
    assert page.source_type == "web_page"
    assert page.needs_media_url is False
    assert "网页正文" in page.message
    assert page.media_url == "https://example.com/article/hello"

    pdf = adapter.resolve("https://cdn.example.com/report.pdf", RequestAuth())
    assert pdf.source_type == "http_document"
    assert pdf.needs_media_url is False
    assert classify_direct_url("https://cdn.example.com/a.docx") == "http_document"


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
                    "alive_conf": {"wx_app_name": "启富课堂"},
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
    assert resolved.author == "启富课堂"


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
                    "user": {"name": "藏龙岛"},
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
    assert resolved.author == "藏龙岛"


@respx.mock
def test_yueniu_reads_start_ts_as_source_time():
    page = "https://jf.yueniuzq.com/living/?id=2cd1f1838b0c122fb50ba1e318d9a907"
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
                    "liveName": "第142轮：20260907——20260911题材梳理课：",
                    "liveStatus": 3,
                    "vipStatus": False,
                    "authorId": "119311606",
                    "startTs": 1788695842,
                    "user": {"name": "藏龙岛"},
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
    assert resolved.created_at is not None
    local = resolved.created_at.astimezone(ZoneInfo("Asia/Shanghai"))
    assert (local.year, local.month, local.day, local.hour, local.minute) == (2026, 9, 6, 19, 57)


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
                    "owner": {"mid": 11430504, "name": "来去由心"},
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
    assert resolved.author == "来去由心"


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


def test_parse_xiaoe_and_bilibili_catalog_id():
    from app.services.ingest.bilibili import parse_bilibili_mid
    from app.services.ingest.xiaoe import parse_xiaoe_catalog_id

    assert parse_xiaoe_catalog_id("appdemo") == "appdemo"
    assert parse_xiaoe_catalog_id("https://appdemo.h5.xiaoeknow.com/v4/course/alive/l_abc?app_id=appdemo") == "appdemo"
    assert parse_bilibili_mid("11430504") == "11430504"
    assert parse_bilibili_mid("https://space.bilibili.com/11430504") == "11430504"


@respx.mock
def test_xiaoe_short_link_to_shop_is_expandable():
    from app.services.ingest.registry import detect_catalog, expand_catalog_short_link

    respx.get("https://etrsz.xetslk.com/sl/shopAbc").mock(
        return_value=Response(
            302, headers={"Location": "https://appdemo.h5.xiaoeknow.com/?app_id=appdemo"}
        )
    )
    respx.get("https://appdemo.h5.xiaoeknow.com/?app_id=appdemo").mock(
        return_value=Response(200, text="<html></html>")
    )
    expanded = expand_catalog_short_link("https://etrsz.xetslk.com/sl/shopAbc", RequestAuth())
    assert expanded == "https://appdemo.h5.xiaoeknow.com/?app_id=appdemo"
    ref = detect_catalog(expanded)
    assert ref is not None
    assert ref.adapter == "xiaoe"
    assert ref.catalog_id == "appdemo"


@respx.mock
def test_xiaoe_short_link_to_single_alive_is_not_catalog():
    import base64
    import json

    from app.services.ingest.registry import detect_catalog, expand_catalog_short_link

    params = base64.b64encode(
        json.dumps(
            {"app_id": "appdtbqcmlu9560", "resource_id": "l_6ab3e1e5e4b023c0862a023d"}
        ).encode()
    ).decode()
    target = f"https://appdtbqcmlu9560.mp.xiaoeknow.com/?app_id=appdtbqcmlu9560&params={params}"
    respx.get("https://etrsz.xetslk.com/sl/2ojTAg").mock(
        return_value=Response(302, headers={"Location": target})
    )
    respx.get(target).mock(return_value=Response(200, text="<html></html>"))

    expanded = expand_catalog_short_link("https://etrsz.xetslk.com/sl/2ojTAg", RequestAuth())
    assert expanded.startswith("https://appdtbqcmlu9560.mp.xiaoeknow.com/")
    assert detect_catalog(expanded) is None


@respx.mock
def test_xiaoe_list_catalog_skips_upcoming():
    from app.services.ingest.xiaoe import XiaoeAdapter

    respx.get("https://appdemo.h5.xiaoeknow.com/p/decorate/homepage").mock(
        return_value=Response(200, text="<html></html>")
    )
    respx.get("https://appdemo.h5.xiaoeknow.com/_alive/v2/list").mock(
        return_value=Response(
            200,
            json={
                "code": 0,
                "data": {
                    "list": [
                        {
                            "id": "l_old",
                            "title": "未开始",
                            "alive_state": 0,
                            "zb_start_at": "2026-08-20 20:00:00",
                        },
                        {
                            "id": "l_done",
                            "title": "8.13行情梳理",
                            "alive_state": 3,
                            "zb_start_at": "2026-08-13 20:00:00",
                            "wx_app_name": "启富课堂",
                        },
                    ]
                },
            },
        )
    )
    items = XiaoeAdapter().list_catalog(RequestAuth(cookie="sid=1"), "appdemo")
    assert [item.source_url for item in items] == [
        "https://appdemo.h5.xiaoeknow.com/v4/course/alive/l_done?app_id=appdemo"
    ]
    assert items[0].title == "8.13行情梳理"
    assert items[0].author == "启富课堂"


@respx.mock
def test_xiaoe_list_catalog_from_shop_homepage():
    import base64
    import json

    from app.services.ingest.xiaoe import XiaoeAdapter

    blob = base64.urlsafe_b64encode(
        json.dumps(
            {"id": "search_bar", "channel_id": "", "component_id": 38901192},
            separators=(",", ":"),
        ).encode()
    ).decode().rstrip("=")
    respx.get("https://appdemo.h5.xiaoeknow.com/p/decorate/homepage").mock(
        return_value=Response(
            200,
            text=(
                '<html>"appdemo","6442073",5,"店铺主页",38901192,"搜索"'
                f"/p/decorate/more/{blob}</html>"
            ),
        )
    )
    respx.post("https://appdemo.h5.xiaoeknow.com/xe.micro_page.h5_more/1.0.0").mock(
        return_value=Response(
            200,
            json={
                "code": 0,
                "msg": "success",
                "data": {
                    "component": {
                        "component_type": "alive",
                        "list": [
                            {
                                "spu_id": "l_new",
                                "type": 4,
                                "title": "9.15行情梳理",
                                "src_type": "alive",
                                "lesson_start_at": "2026-09-15 19:30:00",
                            }
                        ],
                    },
                    "finished": False,
                    "page_num": 1,
                    "last_id": "0_1_0",
                },
            },
        )
    )
    items = XiaoeAdapter().list_catalog(
        RequestAuth(), "https://appdemo.mp.xiaoeknow.com"
    )
    assert [item.title for item in items] == ["9.15行情梳理"]
    assert items[0].source_url == (
        "https://appdemo.h5.xiaoeknow.com/v4/course/alive/l_new?app_id=appdemo"
    )
    assert items[0].created_at is not None
    local = items[0].created_at.astimezone(ZoneInfo("Asia/Shanghai"))
    assert (local.year, local.month, local.day, local.hour) == (2026, 9, 15, 19)


@respx.mock
def test_xiaoe_list_catalog_login_error_mentions_cookie():
    from app.services.ingest.base import CatalogError
    from app.services.ingest.xiaoe import XiaoeAdapter, XIAOE_LOGIN_HINT

    respx.get("https://appdemo.h5.xiaoeknow.com/p/decorate/homepage").mock(
        return_value=Response(200, text="<html></html>")
    )
    respx.get("https://appdemo.h5.xiaoeknow.com/_alive/v2/list").mock(
        return_value=Response(
            200,
            json={"code": 11302, "message": "Redirect.auth.login", "data": {}},
        )
    )
    try:
        XiaoeAdapter().list_catalog(RequestAuth(), "appdemo")
    except CatalogError as exc:
        assert str(exc) == XIAOE_LOGIN_HINT
    else:
        raise AssertionError("expected CatalogError")


@respx.mock
def test_yueniu_list_catalog_requires_cookie():
    from app.services.ingest.base import CatalogError
    from app.services.ingest.yueniu import YueniuAdapter

    try:
        YueniuAdapter().list_catalog(RequestAuth(), "")
        raise AssertionError("应要求 Cookie")
    except CatalogError as exc:
        assert "Cookie" in str(exc)

    respx.get("https://jf.yueniuzq.com/islogin.json").mock(
        return_value=Response(200, json={"success": True, "pptId": "u1"})
    )
    respx.get("https://jf.yueniuzq.com/headGetUserInfo.json").mock(
        return_value=Response(200, json={"muser_webUserId": "u1"})
    )
    respx.get("https://jf.yueniuzq.com/api/live/columnList").mock(
        return_value=Response(
            200,
            json={
                "code": 0,
                "result": {
                    "list": [
                        {
                            "columnId": "col1",
                            "columnName": "盘面课",
                            "authorName": "加菲",
                            "authorId": "author1",
                        }
                    ]
                },
            },
        )
    )
    respx.get("https://jf.yueniuzq.com/api/live/V2/liveList").mock(
        return_value=Response(
            200,
            json={
                "code": 0,
                "result": {
                    "list": [
                        {
                            "liveId": "3f14baab82b61eaf6d47deab521b6f7e",
                            "liveName": "早盘直播",
                            "status": 3,
                            "date": "2026-08-13 12:00:00",
                            "authorName": "加菲",
                        },
                        {
                            "liveId": "upcoming",
                            "liveName": "未开播",
                            "status": 4,
                            "date": "2026-09-20 12:00:00",
                        },
                    ]
                },
            },
        )
    )
    items = YueniuAdapter().list_catalog(RequestAuth(cookie="_xx_ppt_token=abc"), "")
    assert [item.title for item in items] == ["早盘直播"]
    assert items[0].source_url.endswith("id=3f14baab82b61eaf6d47deab521b6f7e")
    assert items[0].author == "加菲"
    assert items[0].created_at is not None


@respx.mock
def test_yueniu_list_catalog_empty_without_login():
    from app.services.ingest.base import CatalogError
    from app.services.ingest.yueniu import YueniuAdapter

    respx.get("https://jf.yueniuzq.com/islogin.json").mock(
        return_value=Response(200, json={"success": False, "message": "logout"})
    )
    try:
        YueniuAdapter().list_catalog(RequestAuth(cookie="_xx_ppt_token=abc"), "")
        raise AssertionError("未登录应提示 Cookie")
    except CatalogError as exc:
        assert "登录" in str(exc)


@respx.mock
def test_bilibili_list_catalog_by_mid():
    from app.services.ingest.bilibili import BilibiliAdapter

    respx.get("https://api.bilibili.com/x/space/arc/search").mock(
        return_value=Response(
            200,
            json={
                "code": 0,
                "data": {
                    "list": {
                        "vlist": [
                            {
                                "bvid": "BV1a4awzsENn",
                                "title": "卖票方法",
                                "author": "来去由心",
                                "created": int(datetime(2026, 8, 13, 4, 0, tzinfo=timezone.utc).timestamp()),
                            }
                        ]
                    }
                },
            },
        )
    )
    items = BilibiliAdapter().list_catalog(RequestAuth(), "https://space.bilibili.com/11430504")
    assert items[0].source_url == "https://www.bilibili.com/video/BV1a4awzsENn"
    assert items[0].title == "卖票方法"
    assert items[0].created_at is not None
    assert items[0].created_at.astimezone(ZoneInfo("Asia/Shanghai")).day == 13


@respx.mock
def test_bilibili_list_catalog_flattens_multiline_cookie():
    from app.services.ingest.bilibili import BilibiliAdapter

    cookies: list[str] = []

    def handler(request):
        cookies.append(request.headers.get("cookie", ""))
        return Response(
            200,
            json={
                "code": 0,
                "data": {
                    "list": {
                        "vlist": [
                            {
                                "bvid": "BV1a4awzsENn",
                                "title": "登录态稿件",
                                "author": "来去由心",
                                "created": 1700000000,
                            }
                        ]
                    }
                },
            },
        )

    respx.get("https://api.bilibili.com/x/web-interface/nav").mock(
        return_value=Response(
            200, json={"code": 0, "data": {"wbi_img": {"img_url": "", "sub_url": ""}}}
        )
    )
    respx.get("https://api.bilibili.com/x/space/arc/search").mock(side_effect=handler)

    auth = RequestAuth(cookie="Buvid=abc\nDedeUserID=396771578\nSESSDATA=xyz")
    items = BilibiliAdapter().list_catalog(auth, "11430504")
    assert items[0].title == "登录态稿件"
    assert cookies
    assert set(cookies) == {"Buvid=abc; DedeUserID=396771578; SESSDATA=xyz"}


@respx.mock
def test_bilibili_list_catalog_keeps_items_when_later_page_rate_limited(monkeypatch):
    from app.services.ingest.bilibili import BilibiliAdapter

    monkeypatch.setattr("app.services.ingest.bilibili.PAGE_PAUSE", 0)
    monkeypatch.setattr("app.services.ingest.bilibili.RETRY_BACKOFF", ())

    def handler(request):
        pn = int(request.url.params.get("pn") or 1)
        if pn == 1:
            vlist = [
                {
                    "bvid": f"BV{index:010d}",
                    "title": f"稿件{index}",
                    "author": "UP",
                    "created": 1700000000,
                }
                for index in range(30)
            ]
            return Response(200, json={"code": 0, "data": {"list": {"vlist": vlist}}})
        return Response(200, json={"code": -799, "message": "请求过于频繁，请稍后再试"})

    respx.get("https://api.bilibili.com/x/space/arc/search").mock(side_effect=handler)
    items = BilibiliAdapter().list_catalog(RequestAuth(), "11430504")
    assert len(items) == 30
    assert items[0].source_url == "https://www.bilibili.com/video/BV0000000000"


@respx.mock
def test_bilibili_list_catalog_retries_then_raises_on_empty_rate_limit(monkeypatch):
    from app.services.ingest.base import CatalogError
    from app.services.ingest.bilibili import BilibiliAdapter

    monkeypatch.setattr("app.services.ingest.bilibili.PAGE_PAUSE", 0)
    monkeypatch.setattr("app.services.ingest.bilibili.RETRY_BACKOFF", ())
    respx.get("https://api.bilibili.com/x/space/arc/search").mock(
        return_value=Response(200, json={"code": -799, "message": "请求过于频繁，请稍后再试"})
    )
    try:
        BilibiliAdapter().list_catalog(RequestAuth(), "11430504")
        raise AssertionError("expected CatalogError")
    except CatalogError as exc:
        assert "限流" in str(exc)


@respx.mock
def test_bilibili_list_catalog_prefers_wbi_search():
    from app.services.ingest.bilibili import BilibiliAdapter

    respx.get("https://api.bilibili.com/x/web-interface/nav").mock(
        return_value=Response(
            200,
            json={
                "code": 0,
                "data": {
                    "wbi_img": {
                        "img_url": "https://i0.hdslb.com/bfs/wbi/" + ("a" * 32) + ".png",
                        "sub_url": "https://i0.hdslb.com/bfs/wbi/" + ("b" * 32) + ".png",
                    }
                },
            },
        )
    )
    respx.get("https://api.bilibili.com/x/space/wbi/arc/search").mock(
        return_value=Response(
            200,
            json={
                "code": 0,
                "data": {
                    "list": {
                        "vlist": [
                            {
                                "bvid": "BV1a4awzsENn",
                                "title": "WBI稿件",
                                "author": "来去由心",
                                "created": 1700000000,
                            }
                        ]
                    }
                },
            },
        )
    )
    items = BilibiliAdapter().list_catalog(RequestAuth(), "11430504")
    assert items[0].title == "WBI稿件"
    assert items[0].source_url == "https://www.bilibili.com/video/BV1a4awzsENn"


def test_detect_catalog_urls():
    from app.services.ingest.registry import detect_catalog

    bili = detect_catalog("https://space.bilibili.com/11430504/video")
    assert bili is not None
    assert bili.adapter == "bilibili"
    assert bili.catalog_id == "11430504"
    assert detect_catalog("https://www.bilibili.com/video/BV1a4awzsENn") is None

    shop = detect_catalog("https://appdemo.h5.xiaoeknow.com/")
    assert shop is not None
    assert shop.adapter == "xiaoe"
    assert shop.catalog_id == "appdemo"
    mp_shop = detect_catalog("https://appdtbqcmlu9560.mp.xiaoeknow.com")
    assert mp_shop is not None
    assert mp_shop.adapter == "xiaoe"
    assert mp_shop.catalog_id == "appdtbqcmlu9560"
    assert detect_catalog("https://appdemo.h5.xiaoeknow.com/v4/course/alive/l_abc?app_id=appdemo") is None

    site = detect_catalog("https://jf.yueniuzq.com/living/")
    assert site is not None
    assert site.adapter == "yueniu"
    assert detect_catalog("https://jf.yueniuzq.com/living/?id=abc") is None


@respx.mock
def test_xiaoe_list_catalog_cursor_second_batch():
    from app.services.ingest.xiaoe import XiaoeAdapter

    respx.get("https://appdemo.h5.xiaoeknow.com/p/decorate/homepage").mock(
        return_value=Response(200, text="<html></html>")
    )

    def handler(request):
        page = int(request.url.params.get("page") or 1)
        if page == 1:
            rows = [
                {"id": f"l_{index}", "title": f"课{index}", "alive_state": 3, "zb_start_at": "2026-08-13 20:00:00"}
                for index in range(20)
            ]
        elif page == 2:
            rows = [
                {"id": "l_next", "title": "第二页", "alive_state": 3, "zb_start_at": "2026-08-12 20:00:00"}
            ]
        else:
            rows = []
        return Response(200, json={"code": 0, "data": {"list": rows}})

    respx.get("https://appdemo.h5.xiaoeknow.com/_alive/v2/list").mock(side_effect=handler)
    first = XiaoeAdapter().list_catalog(RequestAuth(cookie="sid=1"), "appdemo", limit=20)
    assert len(first.items) == 20
    assert first.next_cursor
    second = XiaoeAdapter().list_catalog(
        RequestAuth(cookie="sid=1"), "appdemo", cursor=first.next_cursor, limit=20
    )
    assert [item.title for item in second.items] == ["第二页"]
    assert not second.next_cursor


@respx.mock
def test_bilibili_list_catalog_cursor_and_tid(monkeypatch):
    from app.services.ingest.bilibili import BilibiliAdapter

    monkeypatch.setattr("app.services.ingest.bilibili.PAGE_PAUSE", 0)
    monkeypatch.setattr("app.services.ingest.bilibili.RETRY_BACKOFF", ())
    monkeypatch.setattr("app.services.ingest.bilibili.SPACE_PN_CAP", 1)

    def handler(request):
        pn = int(request.url.params.get("pn") or 1)
        tid = request.url.params.get("tid") or "0"
        if tid == "0":
            vlist = [
                {
                    "bvid": f"BV{index:010d}",
                    "title": f"稿件{index}",
                    "author": "UP",
                    "created": 1700000000,
                }
                for index in range(30)
            ]
            return Response(
                200,
                json={
                    "code": 0,
                    "data": {
                        "list": {
                            "vlist": vlist,
                            "tlist": {"160": {"tid": 160, "count": 1, "name": "生活"}},
                        }
                    },
                },
            )
        return Response(
            200,
            json={
                "code": 0,
                "data": {
                    "list": {
                        "vlist": [
                            {
                                "bvid": "BV9999999999",
                                "title": "分区稿件",
                                "author": "UP",
                                "created": 1690000000,
                            }
                        ]
                    }
                },
            },
        )

    respx.get("https://api.bilibili.com/x/space/arc/search").mock(side_effect=handler)
    first = BilibiliAdapter().list_catalog(RequestAuth(), "11430504", limit=20)
    assert len(first.items) == 20
    assert first.next_cursor
    second = BilibiliAdapter().list_catalog(
        RequestAuth(), "11430504", cursor=first.next_cursor, limit=200
    )
    titles = [item.title for item in second.items]
    assert "稿件20" in titles
    assert "分区稿件" in titles
    assert "稿件0" not in titles
