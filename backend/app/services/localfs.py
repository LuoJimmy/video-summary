"""挂载目录浏览：让界面在「本地任务」里挑选容器内可见的文件或文件夹。"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from math import ceil
from pathlib import Path

from app.config import settings
from app.schemas import LocalEntriesOut, LocalEntryOut, LocalRootOut
from app.services.ingest.base import AUDIO_EXTS, DOCUMENT_EXTS, VIDEO_EXTS

SUPPORTED_EXTS = VIDEO_EXTS | AUDIO_EXTS | DOCUMENT_EXTS
DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200
# 单个文件夹一次能选中的文件数上限，超出后只取前 SCAN_LIMIT 个并提示
SCAN_LIMIT = 1000


class LocalFsError(RuntimeError):
    """浏览失败，message 直接展示给用户。"""


@dataclass
class _PathEntry:
    path: Path
    kind: str
    size: int = 0
    modified_at: datetime | None = None


def browse_root() -> Path:
    """可浏览范围：配了 MEDIA_DIR（Docker 挂载点）就限制在该目录内，本机运行则放开整个文件系统。"""
    raw = (settings.media_dir or "").strip()
    if not raw:
        return Path("/")
    return Path(raw).expanduser().resolve()


def media_root_status() -> LocalRootOut:
    """「本地任务」是否显示挂载目录入口：没配 MEDIA_DIR 或目录不存在时不显示。"""
    raw = (settings.media_dir or "").strip()
    if not raw:
        return LocalRootOut(enabled=False, root="", scan_limit=SCAN_LIMIT)
    root = Path(raw).expanduser().resolve()
    return LocalRootOut(enabled=root.is_dir(), root=str(root), scan_limit=SCAN_LIMIT)


def is_supported_file(path: Path) -> bool:
    return path.suffix.lower() in SUPPORTED_EXTS


def resolve_browse_dir(raw: str = "") -> Path:
    root = browse_root()
    if not root.is_dir():
        raise LocalFsError(
            f"媒体目录 {root} 不存在。Docker 部署请把宿主机目录挂到 {root}（compose 变量 VIDEO_SUMMARY_MEDIA）。"
        )
    text = (raw or "").strip()
    try:
        resolved = (root if not text else Path(text).expanduser()).resolve()
    except OSError as exc:
        raise LocalFsError("无法读取该路径") from exc
    if not resolved.is_dir():
        raise LocalFsError("该路径不是文件夹")
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise LocalFsError(f"只能浏览 {root} 内的文件") from exc
    return resolved


def _visible_items(current: Path) -> list[Path]:
    try:
        items = list(current.iterdir())
    except OSError as exc:
        raise LocalFsError("无法读取该文件夹，请检查挂载权限") from exc
    return [item for item in items if not item.name.startswith(".")]


def _stat(path: Path) -> os.stat_result | None:
    try:
        return path.stat()
    except OSError:
        return None


def _candidates(current: Path) -> list[_PathEntry]:
    dirs: list[Path] = []
    files: list[Path] = []
    for item in _visible_items(current):
        if item.is_dir():
            dirs.append(item)
        elif item.is_file() and is_supported_file(item):
            files.append(item)
    dirs.sort(key=lambda item: item.name.lower())
    files.sort(key=lambda item: item.name.lower())
    found: list[_PathEntry] = []
    for path in dirs:
        if _stat(path) is not None:
            found.append(_PathEntry(path=path, kind="dir"))
    for path in files:
        stat_result = _stat(path)
        if stat_result is None:
            continue
        stamp = stat_result.st_mtime
        found.append(
            _PathEntry(
                path=path,
                kind="file",
                size=stat_result.st_size,
                modified_at=datetime.fromtimestamp(stamp, tz=timezone.utc) if stamp else None,
            )
        )
    return found


def _to_out(item: _PathEntry) -> LocalEntryOut:
    return LocalEntryOut(
        name=item.path.name,
        path=str(item.path),
        kind=item.kind,
        size=item.size,
        modified_at=item.modified_at,
        supported=item.kind == "file",
    )


def _parent(root: Path, current: Path) -> str:
    if current == root:
        return ""
    candidate = current.parent
    if candidate == current:
        return ""
    if candidate == root or root in candidate.parents:
        return str(candidate)
    return ""


def _payload(
    root: Path,
    current: Path,
    entries: list[LocalEntryOut],
    *,
    recursive: bool,
    query: str = "",
    page: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
    total: int = 0,
    truncated: bool = False,
) -> LocalEntriesOut:
    return LocalEntriesOut(
        root=str(root),
        path=str(current),
        parent=_parent(root, current),
        recursive=recursive,
        query=query,
        page=page,
        page_size=page_size,
        total=total,
        entries=entries,
        truncated=truncated,
    )


def list_dir(
    raw: str = "",
    query: str = "",
    page: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
) -> LocalEntriesOut:
    root = browse_root()
    current = resolve_browse_dir(raw)
    keyword = (query or "").strip()
    found = _candidates(current)
    if keyword:
        lowered = keyword.lower()
        found = [item for item in found if lowered in item.path.name.lower()]
    total = len(found)
    size = max(1, min(int(page_size or DEFAULT_PAGE_SIZE), MAX_PAGE_SIZE))
    pages = max(1, ceil(total / size))
    current_page = min(max(1, int(page or 1)), pages)
    start = (current_page - 1) * size
    entries = [_to_out(item) for item in found[start : start + size]]
    return _payload(
        root,
        current,
        entries,
        recursive=False,
        query=keyword,
        page=current_page,
        page_size=size,
        total=total,
    )


def scan_dir(raw: str = "") -> LocalEntriesOut:
    """勾选文件夹时递归收集其中的视频 / 音频 / 文档，最多 SCAN_LIMIT 个。"""
    root = browse_root()
    current = resolve_browse_dir(raw)
    entries: list[LocalEntryOut] = []
    truncated = False
    for folder, subfolders, files in os.walk(current):
        subfolders[:] = sorted(
            (name for name in subfolders if not name.startswith(".")), key=str.lower
        )
        for name in sorted(files, key=str.lower):
            if name.startswith("."):
                continue
            path = Path(folder) / name
            if not is_supported_file(path):
                continue
            if len(entries) >= SCAN_LIMIT:
                truncated = True
                break
            stat_result = _stat(path)
            if stat_result is None:
                continue
            stamp = stat_result.st_mtime
            entries.append(
                LocalEntryOut(
                    name=path.name,
                    path=str(path),
                    kind="file",
                    size=stat_result.st_size,
                    modified_at=datetime.fromtimestamp(stamp, tz=timezone.utc) if stamp else None,
                    supported=True,
                )
            )
        if truncated:
            break
    return _payload(
        root,
        current,
        entries,
        recursive=True,
        page=1,
        page_size=max(1, len(entries)),
        total=len(entries),
        truncated=truncated,
    )
