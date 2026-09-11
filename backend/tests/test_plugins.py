from app.services.plugins import PluginError, describe_plugin, install_plugin, uninstall_plugin


def test_ocr_missing_until_install(tmp_path, monkeypatch):
    from app.config import settings as app_settings

    monkeypatch.setattr(app_settings, "data_dir", tmp_path)
    info = describe_plugin("ocr")
    assert info.status == "missing"


def test_legacy_doc_ready_when_soffice_exists(tmp_path, monkeypatch):
    from app.config import settings as app_settings

    monkeypatch.setattr(app_settings, "data_dir", tmp_path)
    monkeypatch.setattr("app.services.plugins.which_soffice", lambda plugin_root=None: "/usr/bin/soffice")
    info = describe_plugin("legacy_doc")
    assert info.status == "ready"
    assert info.soffice == "/usr/bin/soffice"


def test_install_ocr_writes_ready(tmp_path, monkeypatch):
    from app.config import settings as app_settings

    monkeypatch.setattr(app_settings, "data_dir", tmp_path)

    def fake_install_ocr(dest, progress):
        (dest / "marker.txt").write_text("ok", encoding="utf-8")

    monkeypatch.setattr("app.services.plugins._install_ocr", fake_install_ocr)
    monkeypatch.setattr("app.services.plugins._ocr_importable", lambda dest: True)
    dest = install_plugin("ocr")
    assert (dest / "READY.json").exists()
    assert describe_plugin("ocr").status == "ready"
    uninstall_plugin("ocr")
    assert describe_plugin("ocr").status == "missing"


def test_install_removes_lock_file(tmp_path, monkeypatch):
    from app.config import settings as app_settings
    from app.services.plugins import plugins_root

    monkeypatch.setattr(app_settings, "data_dir", tmp_path)
    monkeypatch.setattr("app.services.plugins._install_ocr", lambda dest, progress: None)
    monkeypatch.setattr("app.services.plugins._ocr_importable", lambda dest: True)
    install_plugin("ocr")
    lock = plugins_root() / ".ocr.lock"
    assert not lock.exists()
    dest = tmp_path / "plugins" / "ocr"
    assert dest.exists()


def test_legacy_doc_without_soffice_errors_on_macos(tmp_path, monkeypatch):
    from app.config import settings as app_settings

    monkeypatch.setattr(app_settings, "data_dir", tmp_path)
    monkeypatch.setattr("app.services.plugins.which_soffice", lambda plugin_root=None: "")
    monkeypatch.setattr("app.services.plugins.platform.system", lambda: "Darwin")
    try:
        install_plugin("legacy_doc")
        raise AssertionError("should fail")
    except PluginError as exc:
        assert "LibreOffice" in str(exc)
        assert describe_plugin("legacy_doc").status == "failed"
