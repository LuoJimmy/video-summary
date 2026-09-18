from app.models import AuthProfile, Site
from app.services.authctx import (
    RequestAuth,
    build_auth,
    http_headers,
    match_site,
    normalize_cookie,
)
from app.services.jsonutil import dumps


def test_match_site_prefers_longer_domain(db_session):
    site = match_site(db_session, "https://etrsz.xetslk.com/sl/q1M06")
    assert site is not None
    assert site.adapter == "xiaoe"

    live = match_site(db_session, "https://jf.yueniuzq.com/living/?id=abc")
    assert live is not None
    assert live.adapter == "yueniu"

    bili = match_site(db_session, "https://www.bilibili.com/video/BV1a4awzsENn")
    assert bili is not None
    assert bili.adapter == "bilibili"


def test_login_profile_shared_across_xiaoe_domains(db_session):
    auth = build_auth(db_session, url="https://shop.xiaoeknow.com/p/course/video/1")
    assert auth.adapter == "xiaoe"
    assert auth.profile is not None
    assert auth.profile.name.startswith("小鹅通")


def test_site_cookie_override_wins(db_session):
    profile = db_session.query(AuthProfile).filter(AuthProfile.name.like("小鹅通%")).one()
    profile.cookie = "from_profile=1"
    site = db_session.query(Site).filter(Site.adapter == "xiaoe").one()
    site.cookie_override = "from_site=1"
    site.extra_headers = dumps({"X-Test": "site"})
    db_session.commit()

    auth = build_auth(db_session, url="https://etrsz.xetslk.com/sl/q1M06")
    assert auth.cookie == "from_site=1"
    assert auth.headers["X-Test"] == "site"


def test_multiline_cookie_is_flattened_before_request(db_session):
    site = db_session.query(Site).filter(Site.adapter == "bilibili").one()
    site.cookie_override = (
        "Cookie: Buvid=ZD49B1D5\n"
        "DedeUserID=396771578\n"
        "\n"
        "SESSDATA=505e96d7%2C1805125990\n"
        "bili_jct=8ba5ffb9"
    )
    db_session.commit()

    auth = build_auth(db_session, url="https://www.bilibili.com/video/BV1a4awzsENn")
    assert auth.cookie == (
        "Buvid=ZD49B1D5; DedeUserID=396771578; SESSDATA=505e96d7%2C1805125990; bili_jct=8ba5ffb9"
    )
    headers = http_headers(auth)
    assert headers["Cookie"] == auth.cookie
    assert not any(char in headers["Cookie"] for char in "\r\n\x00")


def test_normalize_cookie_handles_escaped_and_plain_values():
    assert normalize_cookie("sid=1") == "sid=1"
    assert normalize_cookie("a=1\\nb=2") == "a=1; b=2"
    assert normalize_cookie("a=1;\n\nb=2;") == "a=1; b=2"
    assert normalize_cookie("") == ""


def test_http_headers_stay_single_line():
    auth = RequestAuth(
        cookie="a=1",
        headers={"X-Paste": "line1\nline2", "Cookie": "from_header=2"},
    )
    headers = http_headers(auth)
    assert headers["X-Paste"] == "line1 line2"
    assert headers["Cookie"] == "a=1"

    only_header = http_headers(RequestAuth(headers={"cookie": "x=1\ny=2"}))
    assert only_header["Cookie"] == "x=1; y=2"
