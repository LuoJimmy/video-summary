import pytest

from app.config import settings as app_settings
from app.services.localfs import LocalFsError, list_dir, scan_dir


def _media_tree(tmp_path):
    media = tmp_path / "media"
    (media / "sub").mkdir(parents=True)
    (media / "a.mp4").write_bytes(b"video")
    (media / "archive.zip").write_bytes(b"zip")
    (media / ".hidden.mp4").write_bytes(b"video")
    (media / "sub" / "b.pdf").write_bytes(b"%PDF")
    (media / "sub" / "clip.doc").write_bytes(b"doc")
    return media


def test_list_dir_shows_dirs_and_supported_files(tmp_path, monkeypatch):
    media = _media_tree(tmp_path)
    monkeypatch.setattr(app_settings, "media_dir", str(media))

    payload = list_dir("")
    assert payload.root == str(media)
    assert payload.path == str(media)
    assert payload.parent == ""
    assert payload.recursive is False
    assert payload.total == 2
    assert payload.page == 1
    assert [entry.name for entry in payload.entries] == ["sub", "a.mp4"]
    assert payload.entries[0].kind == "dir"
    assert payload.entries[1].kind == "file"
    assert payload.entries[1].supported is True


def test_list_dir_rejects_path_outside_media_dir(tmp_path, monkeypatch):
    media = _media_tree(tmp_path)
    monkeypatch.setattr(app_settings, "media_dir", str(media))

    with pytest.raises(LocalFsError):
        list_dir(str(tmp_path))
    with pytest.raises(LocalFsError):
        list_dir(str(media / "nope"))

    sub = list_dir(str(media / "sub"))
    assert sub.path == str(media / "sub")
    assert sub.parent == str(media)
    assert [entry.name for entry in sub.entries] == ["b.pdf", "clip.doc"]


def test_scan_dir_collects_supported_files_recursively(tmp_path, monkeypatch):
    media = _media_tree(tmp_path)
    monkeypatch.setattr(app_settings, "media_dir", str(media))

    payload = scan_dir("")
    assert payload.recursive is True
    assert payload.truncated is False
    assert [entry.name for entry in payload.entries] == ["a.mp4", "b.pdf", "clip.doc"]
    assert all(entry.kind == "file" for entry in payload.entries)


def test_local_entries_api(tmp_path, monkeypatch, client):
    media = _media_tree(tmp_path)
    monkeypatch.setattr(app_settings, "media_dir", str(media))

    listed = client.get("/api/jobs/local-entries")
    assert listed.status_code == 200
    body = listed.json()
    assert body["root"] == str(media)
    assert [item["name"] for item in body["entries"]] == ["sub", "a.mp4"]

    scanned = client.get(
        "/api/jobs/local-entries",
        params={"path": str(media / "sub"), "recursive": "true"},
    )
    assert scanned.status_code == 200
    assert [item["name"] for item in scanned.json()["entries"]] == ["b.pdf", "clip.doc"]

    paged = client.get("/api/jobs/local-entries", params={"page": 2, "page_size": 1})
    assert paged.status_code == 200
    assert paged.json()["total"] == 2
    assert [item["name"] for item in paged.json()["entries"]] == ["a.mp4"]

    searched = client.get("/api/jobs/local-entries", params={"query": "MP4"})
    assert searched.status_code == 200
    assert searched.json()["total"] == 1
    assert [item["name"] for item in searched.json()["entries"]] == ["a.mp4"]

    denied = client.get("/api/jobs/local-entries", params={"path": str(tmp_path)})
    assert denied.status_code == 400
    assert "只能浏览" in denied.json()["detail"]


def test_local_entries_api_reports_missing_media_dir(tmp_path, monkeypatch, client):
    monkeypatch.setattr(app_settings, "media_dir", str(tmp_path / "no-media"))

    response = client.get("/api/jobs/local-entries")
    assert response.status_code == 400
    assert "不存在" in response.json()["detail"]


def test_list_dir_paginates_and_searches(tmp_path, monkeypatch):
    media = tmp_path / "media"
    media.mkdir()
    for index in range(5):
        (media / f"clip{index}.mp4").write_bytes(b"video")
    monkeypatch.setattr(app_settings, "media_dir", str(media))

    first = list_dir("", page=1, page_size=2)
    assert first.total == 5
    assert first.page == 1
    assert first.page_size == 2
    assert [entry.name for entry in first.entries] == ["clip0.mp4", "clip1.mp4"]

    third = list_dir("", page=3, page_size=2)
    assert third.page == 3
    assert [entry.name for entry in third.entries] == ["clip4.mp4"]

    overshoot = list_dir("", page=9, page_size=2)
    assert overshoot.page == 3
    assert [entry.name for entry in overshoot.entries] == ["clip4.mp4"]

    searched = list_dir("", query="CLIP3")
    assert searched.query == "CLIP3"
    assert searched.total == 1
    assert [entry.name for entry in searched.entries] == ["clip3.mp4"]


def test_scan_dir_stops_at_limit(tmp_path, monkeypatch):
    from app.services import localfs

    media = tmp_path / "media"
    media.mkdir()
    for index in range(5):
        (media / f"clip{index}.mp4").write_bytes(b"video")
    monkeypatch.setattr(app_settings, "media_dir", str(media))
    monkeypatch.setattr(localfs, "SCAN_LIMIT", 3)

    payload = scan_dir("")
    assert payload.truncated is True
    assert len(payload.entries) == 3


def test_local_root_api(tmp_path, monkeypatch, client):
    media = tmp_path / "media"
    media.mkdir()
    monkeypatch.setattr(app_settings, "media_dir", "")
    disabled = client.get("/api/jobs/local-root").json()
    assert disabled == {"enabled": False, "root": "", "scan_limit": 1000}

    monkeypatch.setattr(app_settings, "media_dir", str(media))
    enabled = client.get("/api/jobs/local-root").json()
    assert enabled["enabled"] is True
    assert enabled["root"] == str(media)

    monkeypatch.setattr(app_settings, "media_dir", str(tmp_path / "gone"))
    assert client.get("/api/jobs/local-root").json()["enabled"] is False
