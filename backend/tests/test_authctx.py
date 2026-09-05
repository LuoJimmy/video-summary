from app.models import AuthProfile, Site
from app.services.authctx import build_auth, match_site
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
