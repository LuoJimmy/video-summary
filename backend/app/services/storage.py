"""uploads 目录的占用统计、播放缓存配额与手动清理。"""

import os
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import settings
from app.models import AppSetting, Job
from app.schemas import StorageArchiveOut, StorageCleanupOut, StorageUsageOut
from app.services.audio_store import ARCHIVE_NAME, WAV_NAME, archive_job_audio

PLAY_NAME = "play.mp4"
SOURCE_PREFIX = "source."
PLAY_QUOTA_KEY = "play_quota_mb"
MEGABYTE = 1024 * 1024


def _files(root: Path) -> list[Path]:
    found: list[Path] = []
    try:
        entries = sorted(root.iterdir())
    except OSError:
        return found
    for entry in entries:
        if entry.is_dir():
            try:
                found.extend(item for item in entry.rglob("*") if item.is_file())
            except OSError:
                continue
        elif entry.is_file():
            found.append(entry)
    return found


def _size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def storage_usage(db: Session) -> StorageUsageOut:
    root = settings.uploads_path().resolve()
    known = {row[0] for row in db.query(Job.id).all()}
    usage = StorageUsageOut(path=str(root), play_quota_bytes=play_quota_bytes(db))
    try:
        entries = sorted(root.iterdir())
    except OSError:
        return usage
    for entry in entries:
        if entry.is_dir() and entry.name not in known:
            usage.orphan_dirs += 1
    for path in _files(root):
        size = _size(path)
        name = path.name
        if name == WAV_NAME:
            usage.wav_files += 1
            usage.wav_bytes += size
        elif name == ARCHIVE_NAME:
            usage.archive_files += 1
            usage.archive_bytes += size
        elif name == PLAY_NAME:
            usage.play_files += 1
            usage.play_bytes += size
        elif name.startswith(SOURCE_PREFIX):
            usage.source_bytes += size
        else:
            usage.other_bytes += size
    usage.total_bytes = (
        usage.wav_bytes
        + usage.archive_bytes
        + usage.play_bytes
        + usage.source_bytes
        + usage.other_bytes
    )
    return usage


def cleanup_audio_archives(db: Session) -> StorageCleanupOut:
    """删掉 uploads 下所有 opus 归档；删后重转写会按原始地址重新抽音。"""
    root = settings.uploads_path().resolve()
    removed = 0
    freed = 0
    for path in sorted(root.rglob(ARCHIVE_NAME)):
        try:
            path.resolve().relative_to(root)
            if not path.is_file():
                continue
            size = path.stat().st_size
            path.unlink()
        except (OSError, ValueError):
            continue
        removed += 1
        freed += size
    return StorageCleanupOut(removed_files=removed, freed_bytes=freed, usage=storage_usage(db))


def archive_existing_wavs(db: Session) -> StorageArchiveOut:
    """把任务目录里还留着的 audio.wav 压成 opus 归档，用于升级后的存量整理。"""
    root = settings.uploads_path().resolve()
    archived = 0
    saved = 0
    failed = 0
    for path in sorted(root.rglob(WAV_NAME)):
        try:
            path.resolve().relative_to(root)
            if not path.is_file() or path.stat().st_size <= 0:
                continue
            before = path.stat().st_size
        except (OSError, ValueError):
            continue
        result = archive_job_audio(path.parent.name, path)
        if result is None:
            failed += 1
            continue
        archived += 1
        saved += max(0, before - _size(result))
    return StorageArchiveOut(
        archived_files=archived,
        saved_bytes=saved,
        failed_files=failed,
        usage=storage_usage(db),
    )


def play_quota_bytes(db: Session) -> int:
    """设置页填的播放缓存上限（字节）；0 表示不限制。"""
    from app.services.settings_store import parse_play_quota_mb

    row = db.get(AppSetting, PLAY_QUOTA_KEY)
    return parse_play_quota_mb(row.value if row else "") * MEGABYTE


def play_cache_entries() -> list[tuple[Path, int, float]]:
    """所有 play.mp4 的（路径, 大小, 最近播放时间）；时间用 mtime/atime 里较新的那个。"""
    root = settings.uploads_path().resolve()
    entries: list[tuple[Path, int, float]] = []
    for path in sorted(root.rglob(PLAY_NAME)):
        try:
            path.resolve().relative_to(root)
            stat = path.stat()
        except (OSError, ValueError):
            continue
        if stat.st_size <= 0:
            continue
        entries.append((path, stat.st_size, max(stat.st_mtime, stat.st_atime)))
    return entries


def enforce_play_quota(db: Session, protect_job_id: str = "") -> StorageCleanupOut:
    """超出上限时按最久未播放的顺序删 play.mp4；未配置上限（0）时什么都不做。"""
    quota = play_quota_bytes(db)
    entries = play_cache_entries()
    total = sum(size for _, size, _ in entries)
    removed = 0
    freed = 0
    if quota > 0 and total > quota:
        for path, size, _ in sorted(entries, key=lambda item: item[2]):
            if total <= quota:
                break
            if protect_job_id and path.parent.name == protect_job_id:
                continue
            try:
                path.unlink()
            except OSError:
                continue
            removed += 1
            freed += size
            total -= size
    return StorageCleanupOut(
        removed_files=removed,
        freed_bytes=freed,
        usage=storage_usage(db),
    )


def mark_play_used(path: Path) -> None:
    """播放命中缓存时刷新时间戳，让 LRU 认得出「最近没看过」。"""
    try:
        os.utime(path)
    except OSError:
        pass
