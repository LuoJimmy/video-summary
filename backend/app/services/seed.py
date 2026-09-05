from sqlalchemy.orm import Session

from app.models import AuthProfile, Site
from app.services.jsonutil import dumps


def seed_defaults(db: Session) -> None:
    xiaoe_profile = _ensure_profile(
        db,
        "小鹅通登录档案",
        "把浏览器里 xetslk.com / xiaoeknow.com 的 Cookie 粘到这里，可同时打通短链与店铺域。",
    )
    yueniu_profile = _ensure_profile(
        db,
        "加菲财经/约牛登录档案",
        "把 jf.yueniuzq.com 的 Cookie 粘到这里，直播域 jflive.yueniuzq.com 会一并带上。",
    )
    bili_profile = _ensure_profile(
        db,
        "B站登录档案",
        "公开视频可不填。大会员或需登录的稿件，把 www.bilibili.com 的 Cookie（含 SESSDATA）粘到这里。",
    )
    db.flush()
    _ensure_site(
        db,
        name="小鹅通",
        adapter="xiaoe",
        patterns=["xetslk.com", "xiaoeknow.com", "xiaoe-tech.com", "xet.tech", "xed.plus", "xiaoet.cn"],
        profile_id=xiaoe_profile.id,
        notes="示例：https://etrsz.xetslk.com/sl/q1M06",
    )
    _ensure_site(
        db,
        name="加菲财经/约牛",
        adapter="yueniu",
        patterns=["yueniuzq.com", "yueniusz.com"],
        profile_id=yueniu_profile.id,
        notes="示例：https://jf.yueniuzq.com/living/?id=3f14baab82b61eaf6d47deab521b6f7e",
    )
    _ensure_site(
        db,
        name="B站",
        adapter="bilibili",
        patterns=["bilibili.com", "b23.tv", "bili2233.cn"],
        profile_id=bili_profile.id,
        notes="示例：https://www.bilibili.com/video/BV1a4awzsENn",
    )
    _ensure_site(
        db,
        name="通用直链",
        adapter="generic",
        patterns=[],
        profile_id=None,
        notes="本地文件、公开 mp4/m3u8，或不匹配其他站点时使用。",
    )
    db.commit()


def _ensure_profile(db: Session, name: str, notes: str) -> AuthProfile:
    row = db.query(AuthProfile).filter(AuthProfile.name == name).first()
    if row:
        return row
    row = AuthProfile(name=name, notes=notes)
    db.add(row)
    return row


def _ensure_site(
    db: Session,
    name: str,
    adapter: str,
    patterns: list[str],
    profile_id: str | None,
    notes: str,
) -> Site:
    row = db.query(Site).filter(Site.adapter == adapter).first()
    if row:
        return row
    row = Site(
        name=name,
        adapter=adapter,
        domain_patterns=dumps(patterns),
        auth_profile_id=profile_id,
        notes=notes,
    )
    db.add(row)
    return row
