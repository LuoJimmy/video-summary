import threading
import time

from app.services.plugins import (
    PluginCancelled,
    PluginError,
    cancel_plugin_install,
    describe_plugin,
    install_plugin,
    mark_plugin_install_started,
    plugins_root,
    raise_if_plugin_cancelled,
    uninstall_plugin,
)


def test_ocr_missing_until_install(tmp_path, monkeypatch):
    from app.config import settings as app_settings

    monkeypatch.setattr(app_settings, "data_dir", tmp_path)
    from app.services.plugins import _installs

    _installs.clear()
    info = describe_plugin("ocr")
    assert info.status == "missing"


def test_legacy_doc_ready_when_soffice_exists(tmp_path, monkeypatch):
    from app.config import settings as app_settings

    monkeypatch.setattr(app_settings, "data_dir", tmp_path)
    from app.services.plugins import _installs

    _installs.clear()
    monkeypatch.setattr("app.services.plugins.which_soffice", lambda plugin_root=None: "/usr/bin/soffice")
    info = describe_plugin("legacy_doc")
    assert info.status == "ready"
    assert info.soffice == "/usr/bin/soffice"


def test_install_ocr_writes_ready(tmp_path, monkeypatch):
    from app.config import settings as app_settings

    monkeypatch.setattr(app_settings, "data_dir", tmp_path)
    from app.services.plugins import _installs

    _installs.clear()

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
    from app.services.plugins import _installs

    _installs.clear()
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
    from app.services.plugins import _installs

    _installs.clear()
    monkeypatch.setattr("app.services.plugins.which_soffice", lambda plugin_root=None: "")
    monkeypatch.setattr("app.services.plugins.platform.system", lambda: "Darwin")
    try:
        install_plugin("legacy_doc")
        raise AssertionError("should fail")
    except PluginError as exc:
        assert "LibreOffice" in str(exc)
        assert describe_plugin("legacy_doc").status == "failed"


def test_uninstall_while_installing_rejected(tmp_path, monkeypatch):
    from app.config import settings as app_settings

    monkeypatch.setattr(app_settings, "data_dir", tmp_path)
    from app.services.plugins import _installs

    _installs.clear()
    lock = plugins_root() / ".ocr.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text("queued", encoding="utf-8")
    try:
        uninstall_plugin("ocr")
        raise AssertionError("should fail")
    except PluginError as exc:
        assert "取消" in str(exc)
    assert describe_plugin("ocr").status == "installing"


def test_cancel_install_resets_to_missing(tmp_path, monkeypatch):
    from app.config import settings as app_settings

    monkeypatch.setattr(app_settings, "data_dir", tmp_path)
    from app.services.plugins import _installs

    _installs.clear()
    started = threading.Event()
    errors: list[BaseException] = []

    def fake_install_ocr(dest, progress):
        started.set()
        while True:
            raise_if_plugin_cancelled()
            time.sleep(0.02)

    monkeypatch.setattr("app.services.plugins._install_ocr", fake_install_ocr)

    def run():
        try:
            install_plugin("ocr")
        except PluginCancelled:
            return
        except BaseException as exc:
            errors.append(exc)

    mark_plugin_install_started("ocr")
    (plugins_root() / ".ocr.lock").write_text("queued", encoding="utf-8")
    thread = threading.Thread(target=run)
    thread.start()
    assert started.wait(timeout=2)
    assert describe_plugin("ocr").status == "installing"
    info = cancel_plugin_install("ocr")
    assert info.status == "missing"
    thread.join(timeout=2)
    assert not thread.is_alive()
    assert describe_plugin("ocr").status == "missing"
    assert errors == []


def test_cancel_without_install_errors(tmp_path, monkeypatch):
    from app.config import settings as app_settings

    monkeypatch.setattr(app_settings, "data_dir", tmp_path)
    from app.services.plugins import _installs

    _installs.clear()
    try:
        cancel_plugin_install("ocr")
        raise AssertionError("should fail")
    except PluginError as exc:
        assert "没有正在安装" in str(exc)
