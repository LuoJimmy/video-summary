from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from app.config import settings
from app.services.httpclient import http_client


class PluginError(RuntimeError):
    """插件安装或加载失败。"""


ProgressCb = Callable[[int, str], None]

PLUGIN_IDS = ("ocr", "legacy_doc")
LIBREOFFICE_VERSION = "25.2.5"
READY_NAME = "READY.json"
ERROR_NAME = "ERROR.txt"


@dataclass
class PluginInfo:
    id: str
    title: str
    description: str
    size_hint: str
    status: str
    error: str = ""
    soffice: str = ""


def plugins_root() -> Path:
    path = settings.data_dir / "plugins"
    path.mkdir(parents=True, exist_ok=True)
    return path


def plugin_dir(plugin_id: str) -> Path:
    path = plugins_root() / plugin_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def list_plugins() -> list[PluginInfo]:
    return [describe_plugin(item) for item in PLUGIN_IDS]


def describe_plugin(plugin_id: str) -> PluginInfo:
    specs = {
        "ocr": (
            "扫描件 OCR",
            "识别无文字层的扫描 PDF。首次安装会把 RapidOCR 与模型下载到数据目录。",
            "约 100–200MB，装到数据盘",
        ),
        "legacy_doc": (
            "旧版 Word（.doc）",
            "优先使用系统 LibreOffice。Linux 上若没有，会把官方包下到数据目录。",
            "系统已装则不占额外空间；否则约 300MB",
        ),
    }
    title, description, size_hint = specs.get(plugin_id, (plugin_id, "", ""))
    status, error, soffice = _status_fields(plugin_id)
    return PluginInfo(
        id=plugin_id,
        title=title,
        description=description,
        size_hint=size_hint,
        status=status,
        error=error,
        soffice=soffice,
    )


def ensure_plugin(plugin_id: str, progress: ProgressCb | None = None) -> Path:
    if plugin_id not in PLUGIN_IDS:
        raise PluginError(f"未知插件：{plugin_id}")
    info = describe_plugin(plugin_id)
    if info.status == "ready":
        return plugin_dir(plugin_id)
    return install_plugin(plugin_id, progress=progress)


def install_plugin(plugin_id: str, progress: ProgressCb | None = None) -> Path:
    if plugin_id not in PLUGIN_IDS:
        raise PluginError(f"未知插件：{plugin_id}")
    dest = plugin_dir(plugin_id)
    lock_path = plugins_root() / f".{plugin_id}.lock"
    _report(progress, 5, f"正在安装{describe_plugin(plugin_id).title}…")
    with _file_lock(lock_path):
        info = describe_plugin(plugin_id)
        if info.status == "ready":
            return dest
        _write_error(dest, "")
        try:
            if plugin_id == "ocr":
                _install_ocr(dest, progress)
            else:
                _install_legacy_doc(dest, progress)
            _write_ready(dest, extra={"soffice": which_soffice(dest) or ""})
            _report(progress, 100, "插件已就绪")
        except Exception as exc:
            message = str(exc) if isinstance(exc, PluginError) else f"插件安装失败：{exc}"
            _write_error(dest, message)
            raise PluginError(message) from exc
    return dest


def uninstall_plugin(plugin_id: str) -> None:
    if plugin_id not in PLUGIN_IDS:
        raise PluginError(f"未知插件：{plugin_id}")
    dest = plugin_dir(plugin_id)
    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)
    dest.mkdir(parents=True, exist_ok=True)


def ensure_ocr_engine(progress=None):
    dest = ensure_plugin("ocr", progress=progress)
    _prepare_ocr_env(dest)
    try:
        from rapidocr_onnxruntime import RapidOCR
    except ImportError as exc:
        raise PluginError("OCR 插件未正确安装，请到设置页重新安装扫描件 OCR") from exc
    try:
        return RapidOCR()
    except Exception as exc:
        raise PluginError(f"OCR 引擎启动失败：{exc}") from exc


def convert_doc_with_soffice(path: Path, dest_dir: Path) -> Path:
    binary = which_soffice()
    if not binary:
        raise PluginError("未安装 LibreOffice，无法处理旧版 .doc。请到设置页安装「旧版 Word」插件，或在本机安装 LibreOffice。")
    dest_dir.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(
            [binary, "--headless", "--norestore", "--convert-to", "docx", "--outdir", str(dest_dir), str(path)],
            check=True,
            capture_output=True,
            text=True,
            timeout=180,
        )
    except subprocess.TimeoutExpired as exc:
        raise PluginError("LibreOffice 转换超时") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or str(exc)).strip()
        raise PluginError(f"LibreOffice 转换失败：{detail or exc}") from exc
    converted = dest_dir / f"{path.stem}.docx"
    if not converted.exists():
        matches = list(dest_dir.glob("*.docx"))
        if not matches:
            raise PluginError("LibreOffice 没有生成 .docx")
        converted = matches[0]
    return converted


def which_soffice(plugin_root: Path | None = None) -> str:
    env_path = (os.environ.get("LIBREOFFICE_BIN") or "").strip()
    if env_path and Path(env_path).exists():
        return env_path
    for name in ("soffice", "libreoffice"):
        found = shutil.which(name)
        if found:
            return found
    search_roots = [plugin_root] if plugin_root else [plugin_dir("legacy_doc")]
    for root in search_roots:
        if root is None or not root.exists():
            continue
        for candidate in root.rglob("soffice"):
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return str(candidate)
        for candidate in root.rglob("soffice.bin"):
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return str(candidate)
    mac = Path("/Applications/LibreOffice.app/Contents/MacOS/soffice")
    if mac.exists():
        return str(mac)
    return ""


def _status_fields(plugin_id: str) -> tuple[str, str, str]:
    dest = plugin_dir(plugin_id)
    lock_path = plugins_root() / f".{plugin_id}.lock"
    if lock_path.exists():
        try:
            if time.time() - lock_path.stat().st_mtime < 1800:
                return "installing", "", ""
        except OSError:
            pass
    error = _read_error(dest)
    if plugin_id == "legacy_doc":
        soffice = which_soffice(dest)
        if soffice:
            return "ready", "", soffice
        if error:
            return "failed", error, ""
        return "missing", "", ""
    ready_file = dest / READY_NAME
    if ready_file.exists() and _ocr_importable(dest):
        return "ready", "", ""
    if error:
        return "failed", error, ""
    return "missing", "", ""


def _ocr_importable(dest: Path) -> bool:
    _prepare_ocr_env(dest)
    try:
        __import__("rapidocr_onnxruntime")
        return True
    except Exception:
        return False


def _prepare_ocr_env(dest: Path) -> None:
    target = str(dest)
    if target not in sys.path:
        sys.path.insert(0, target)
    models = dest / "models"
    models.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("RAPIDOCR_HOME", str(models))


def _install_ocr(dest: Path, progress: ProgressCb | None) -> None:
    _report(progress, 15, "正在下载 OCR 依赖…")
    command = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--upgrade",
        "--target",
        str(dest),
        "rapidocr-onnxruntime",
    ]
    try:
        subprocess.run(command, check=True, capture_output=True, text=True, timeout=600)
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or str(exc)).strip()
        raise PluginError(f"安装 OCR 插件失败：{detail or 'pip 安装出错'}。请检查网络后到设置页重试。") from exc
    except subprocess.TimeoutExpired as exc:
        raise PluginError("安装 OCR 插件超时，请检查网络后重试") from exc
    _report(progress, 80, "正在检查 OCR 引擎…")
    _prepare_ocr_env(dest)
    try:
        from rapidocr_onnxruntime import RapidOCR

        RapidOCR()
    except Exception as exc:
        raise PluginError(f"OCR 引擎无法启动：{exc}") from exc


def _install_legacy_doc(dest: Path, progress: ProgressCb | None) -> None:
    existing = which_soffice(dest)
    if existing:
        _report(progress, 100, "已检测到系统 LibreOffice")
        return
    system = platform.system().lower()
    if system != "linux":
        raise PluginError(
            "未安装 LibreOffice。macOS 可用 brew install --cask libreoffice，"
            "Windows 请从官网安装。装好后回到设置页点安装，或把 soffice 放到数据目录 plugins/legacy_doc。"
        )
    _report(progress, 20, "正在下载 LibreOffice…")
    url = _libreoffice_url()
    archive = dest / "libreoffice-download"
    archive.parent.mkdir(parents=True, exist_ok=True)
    _download_file(url, archive, progress)
    _report(progress, 70, "正在解压 LibreOffice…")
    _extract_libreoffice(archive, dest)
    archive.unlink(missing_ok=True)
    if not which_soffice(dest):
        raise PluginError("LibreOffice 解压后找不到 soffice，请到设置页重试或在主机安装 LibreOffice")


def _libreoffice_url() -> str:
    machine = platform.machine().lower()
    version = LIBREOFFICE_VERSION
    if machine in {"aarch64", "arm64"}:
        arch = "aarch64"
        name = f"LibreOffice_{version}_Linux_aarch64_deb.tar.gz"
    else:
        arch = "x86_64"
        name = f"LibreOffice_{version}_Linux_x86-64_deb.tar.gz"
    return f"https://download.documentfoundation.org/libreoffice/stable/{version}/deb/{arch}/{name}"


def _download_file(url: str, dest: Path, progress: ProgressCb | None) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with http_client(timeout=120.0, follow_redirects=True) as client:
        try:
            with client.stream("GET", url) as response:
                response.raise_for_status()
                total = int(response.headers.get("content-length") or 0)
                done = 0
                with dest.open("wb") as handle:
                    for chunk in response.iter_bytes(1024 * 256):
                        handle.write(chunk)
                        done += len(chunk)
                        if total:
                            pct = 20 + int(45 * done / total)
                            _report(progress, min(65, pct), "正在下载 LibreOffice…")
        except Exception as exc:
            dest.unlink(missing_ok=True)
            raise PluginError(f"下载 LibreOffice 失败：{exc}。请检查网络后到设置页重试。") from exc


def _extract_libreoffice(archive: Path, dest: Path) -> None:
    extract_root = dest / "bundle"
    extract_root.mkdir(parents=True, exist_ok=True)
    try:
        with tarfile.open(archive, "r:*") as tar:
            tar.extractall(extract_root)
    except Exception as exc:
        raise PluginError(f"解压 LibreOffice 失败：{exc}") from exc
    debs = sorted(extract_root.rglob("*.deb"))
    main = [item for item in debs if "helppack" not in item.name.lower() and "sdk" not in item.name.lower()]
    if not main:
        raise PluginError("LibreOffice 安装包里没有找到 deb")
    _extract_deb(main[0], dest)
    shutil.rmtree(extract_root, ignore_errors=True)


def _extract_deb(deb_path: Path, dest: Path) -> None:
    data_tar = _ar_member(deb_path, prefix="data.tar")
    if data_tar is None:
        raise PluginError("无法从 LibreOffice deb 中取出 data.tar")
    name, payload = data_tar
    tmp = dest / name
    tmp.write_bytes(payload)
    try:
        with tarfile.open(tmp, "r:*") as tar:
            tar.extractall(dest)
    finally:
        tmp.unlink(missing_ok=True)


def _ar_member(path: Path, prefix: str) -> tuple[str, bytes] | None:
    data = path.read_bytes()
    if not data.startswith(b"!<arch>\n"):
        return None
    offset = 8
    while offset + 60 <= len(data):
        header = data[offset : offset + 60]
        name = header[0:16].decode("ascii", errors="ignore").strip()
        size_text = header[48:58].decode("ascii", errors="ignore").strip()
        try:
            size = int(size_text)
        except ValueError:
            break
        offset += 60
        payload = data[offset : offset + size]
        offset += size + (size % 2)
        if name.startswith(prefix):
            return name.strip("/"), payload
    return None


def _file_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)

    class _Lock:
        def __enter__(self):
            self.handle = path.open("w")
            try:
                import fcntl

                fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX)
            except Exception:
                pass
            self.handle.write(str(os.getpid()))
            self.handle.flush()
            return self

        def __exit__(self, exc_type, exc, tb):
            try:
                import fcntl

                fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
            except Exception:
                pass
            self.handle.close()
            path.unlink(missing_ok=True)

    return _Lock()


def _write_ready(dest: Path, extra: dict | None = None) -> None:
    payload = {"ok": True, **(extra or {})}
    (dest / READY_NAME).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    (dest / ERROR_NAME).unlink(missing_ok=True)


def _write_error(dest: Path, message: str) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    if message:
        (dest / ERROR_NAME).write_text(message, encoding="utf-8")
    else:
        (dest / ERROR_NAME).unlink(missing_ok=True)


def _read_error(dest: Path) -> str:
    path = dest / ERROR_NAME
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8").strip()


def _report(progress: ProgressCb | None, pct: int, message: str) -> None:
    if progress:
        progress(pct, message)
