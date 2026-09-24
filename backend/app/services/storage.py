"""uploads 目录的占用统计与手动清理。"""

from pathlib import Path

from sqlalchemy.orm import Session

from app.config import settings
from app.models import Job
from app.schemas import StorageArchiveOut, StorageCleanupOut, StorageUsageOut
from app.services.audio_store import ARCHIVE_NAME, WAV_NAME, archive_job_audio

PLAY_NAME = "play.mp4"
SOURCE_PREFIX = "source."


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
    usage = StorageUsageOut(path=str(root))
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
