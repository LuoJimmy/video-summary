from app.models import Job
from app.services.ingest.base import ResolvedMedia
from app.services.sourceauthor import backfill_job_authors, normalize_author


def test_normalize_author_trims_and_caps():
    assert normalize_author("  藏龙岛  ") == "藏龙岛"
    assert normalize_author("x" * 200) == "x" * 120
    assert normalize_author(None) == ""


def test_backfill_job_authors_from_resolve_and_site_fallback(db_session, monkeypatch):
    site_id = "site-yueniu"
    resolved = Job(
        title="已解析",
        source_url="https://jf.yueniuzq.com/living/?id=a",
        site_id=site_id,
        status="done",
    )
    offline = Job(
        title="已下架",
        source_url="https://jf.yueniuzq.com/living/?id=b",
        site_id=site_id,
        status="done",
    )
    kept = Job(
        title="已有作者",
        author="藏龙岛",
        source_url="https://jf.yueniuzq.com/living/?id=c",
        site_id=site_id,
        status="done",
    )
    lonely = Job(
        title="无站点同伴",
        source_url="https://cdn.example.com/a.mp4",
        site_id="site-other",
        status="done",
    )
    db_session.add_all([resolved, offline, kept, lonely])
    db_session.commit()

    def fake_resolve(url, auth, media_url_override=""):
        if url.endswith("id=a"):
            return ResolvedMedia(adapter="yueniu", source_type="hls", author="藏龙岛")
        return ResolvedMedia(adapter="yueniu", source_type="live", author="")

    monkeypatch.setattr("app.services.ingest.resolve_media", fake_resolve)
    result = backfill_job_authors(db_session)
    db_session.refresh(resolved)
    db_session.refresh(offline)
    db_session.refresh(kept)
    db_session.refresh(lonely)
    assert resolved.author == "藏龙岛"
    assert offline.author == "藏龙岛"
    assert kept.author == "藏龙岛"
    assert lonely.author == ""
    assert (resolved.id, "藏龙岛") in result["resolved"]
    assert (offline.id, "藏龙岛") in result["fallback"]
