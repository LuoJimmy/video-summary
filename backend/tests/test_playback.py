from pathlib import Path

from app.models import Job, Site
from app.services.ingest.base import ResolvedMedia
from app.services.playback import (
    browser_playback_url,
    ensure_play_file,
    looks_expiring,
    needs_play_proxy,
    refresh_job_media,
    should_refresh_media,
)


def test_signed_xiaoe_url_looks_expiring():
    url = "https://encrypt-k-vod.xet.tech/a/playlist_eof.m3u8?sign=6b4f85f4&t=6a80ccc3&us=jAEAOgleII"
    assert looks_expiring(url) is True


def test_bilibili_m4s_needs_play_proxy():
    assert needs_play_proxy("https://upos.example.com/a.m4s", "bilibili", "http_audio") is True
    assert needs_play_proxy("https://cdn.example.com/a.m3u8", "xiaoe", "hls") is False
    assert needs_play_proxy("/tmp/a.mp4", "generic", "local_file") is True


def test_local_job_does_not_refresh(db_session):
    job = Job(title="本地", source_url="/tmp/a.mp4", media_url="/tmp/a.mp4", status="done")
    db_session.add(job)
    db_session.commit()
    url, refreshed, message = refresh_job_media(db_session, job)
    assert refreshed is False
    assert url == f"/api/jobs/{job.id}/play"
    assert job.media_url == "/tmp/a.mp4"
    assert message == ""


def test_refresh_xiaoe_ignores_stale_override(db_session, monkeypatch):
    site = db_session.query(Site).filter(Site.adapter == "xiaoe").one()
    job = Job(
        title="旧课",
        source_url="https://etrsz.xetslk.com/sl/q1M06",
        site_id=site.id,
        media_url="https://encrypt-k-vod.xet.tech/old/playlist_eof.m3u8?sign=old&t=1",
        media_url_override="https://encrypt-k-vod.xet.tech/old/playlist_eof.m3u8?sign=old&t=1",
        status="done",
    )
    db_session.add(job)
    db_session.commit()
    captured = {}

    def fake_resolve(url, auth, media_url_override=""):
        captured["override"] = media_url_override
        captured["url"] = url
        return ResolvedMedia(
            adapter="xiaoe",
            source_type="hls",
            media_url="https://encrypt-k-vod.xet.tech/new/playlist_eof.m3u8?sign=new&t=9",
        )

    monkeypatch.setattr("app.services.playback.resolve_media", fake_resolve)
    url, refreshed, message = refresh_job_media(db_session, job)
    assert captured["override"] == ""
    assert captured["url"].endswith("/sl/q1M06")
    assert refreshed is True
    assert "sign=new" in url
    assert job.media_url == url
    assert message == ""


def test_refresh_keeps_old_url_when_resolve_fails(db_session, monkeypatch):
    site = db_session.query(Site).filter(Site.adapter == "xiaoe").one()
    stale = "https://encrypt-k-vod.xet.tech/old/playlist_eof.m3u8?sign=old&t=1"
    job = Job(
        title="旧课",
        source_url="https://etrsz.xetslk.com/sl/q1M06",
        site_id=site.id,
        media_url=stale,
        status="done",
    )
    db_session.add(job)
    db_session.commit()

    def fake_resolve(url, auth, media_url_override=""):
        return ResolvedMedia(adapter="xiaoe", source_type="page", needs_media_url=True, message="Cookie 失效")

    monkeypatch.setattr("app.services.playback.resolve_media", fake_resolve)
    url, refreshed, message = refresh_job_media(db_session, job)
    assert refreshed is False
    assert url == stale
    assert "Cookie" in message


def test_should_refresh_xiaoe_even_without_sign_query():
    job = Job(source_url="https://etrsz.xetslk.com/sl/q1M06", media_url="https://cdn.example.com/a.m3u8")
    assert should_refresh_media(job, "xiaoe") is True


def test_job_media_endpoint_refreshes(client, db_session, monkeypatch):
    site = db_session.query(Site).filter(Site.adapter == "xiaoe").one()
    job = Job(
        title="旧课",
        source_url="https://etrsz.xetslk.com/sl/q1M06",
        site_id=site.id,
        media_url="https://encrypt-k-vod.xet.tech/old/playlist_eof.m3u8?sign=old&t=1",
        status="done",
    )
    db_session.add(job)
    db_session.commit()

    def fake_resolve(url, auth, media_url_override=""):
        return ResolvedMedia(
            adapter="xiaoe",
            source_type="hls",
            media_url="https://encrypt-k-vod.xet.tech/new/playlist_eof.m3u8?sign=new&t=9",
        )

    monkeypatch.setattr("app.services.playback.resolve_media", fake_resolve)
    response = client.get(f"/api/jobs/{job.id}/media")
    assert response.status_code == 200
    payload = response.json()
    assert payload["refreshed"] is True
    assert "sign=new" in payload["url"]


def test_bilibili_media_uses_play_proxy(client, db_session, monkeypatch):
    site = db_session.query(Site).filter(Site.adapter == "bilibili").one()
    job = Job(
        title="B站课",
        source_url="https://www.bilibili.com/video/BV1a4awzsENn",
        site_id=site.id,
        source_type="http_audio",
        media_url="https://upos.example.com/old.m4s",
        status="done",
    )
    db_session.add(job)
    db_session.commit()

    def fake_resolve(url, auth, media_url_override=""):
        return ResolvedMedia(
            adapter="bilibili",
            source_type="http_audio",
            media_url="https://upos.example.com/192k.m4s",
            extra={
                "play_video_url": "https://upos.example.com/720.m4s",
                "play_audio_url": "https://upos.example.com/192k.m4s",
            },
        )

    monkeypatch.setattr("app.services.playback.resolve_media", fake_resolve)
    response = client.get(f"/api/jobs/{job.id}/media")
    assert response.status_code == 200
    payload = response.json()
    assert payload["refreshed"] is True
    assert payload["url"] == f"/api/jobs/{job.id}/play"
    db_session.refresh(job)
    assert job.media_url.endswith("192k.m4s")


def test_play_endpoint_serves_local_mp4(client, db_session, tmp_path):
    video = tmp_path / "talk.mp4"
    video.write_bytes(b"fake-mp4-bytes")
    job = Job(
        title="本地",
        source_url=str(video),
        source_path=str(video),
        media_url=str(video),
        source_type="local_file",
        status="done",
    )
    db_session.add(job)
    db_session.commit()
    response = client.get(f"/api/jobs/{job.id}/play")
    assert response.status_code == 200
    assert response.content == b"fake-mp4-bytes"
    assert "video/mp4" in response.headers.get("content-type", "")
    assert "inline" in (response.headers.get("content-disposition") or "").lower()


def test_ensure_play_file_uses_cached_mp4(db_session, tmp_path, monkeypatch):
    job = Job(
        title="B站课",
        source_url="https://www.bilibili.com/video/BV1a4awzsENn",
        media_url="https://upos.example.com/a.m4s",
        status="done",
    )
    db_session.add(job)
    db_session.commit()
    cached = tmp_path / "play.mp4"
    cached.write_bytes(b"cached")
    monkeypatch.setattr("app.services.playback.cached_play_file", lambda _job_id: cached)
    path = ensure_play_file(db_session, job)
    assert path == cached


def test_browser_playback_url_keeps_hls():
    job = Job(id="abc", source_url="https://etrsz.xetslk.com/sl/q1M06")
    url = browser_playback_url(
        job,
        "https://encrypt-k-vod.xet.tech/a.m3u8?sign=1",
        "xiaoe",
        ResolvedMedia(adapter="xiaoe", source_type="hls"),
    )
    assert url.endswith(".m3u8?sign=1")
