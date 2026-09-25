from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import (
    AppSettingsIn,
    AppSettingsOut,
    DomainPresetCreateIn,
    StorageArchiveOut,
    StorageCleanupOut,
    StorageUsageOut,
)
from app.services.domain import add_preset, delete_preset
from app.services.settings_store import load_settings, save_settings
from app.services.storage import (
    archive_existing_wavs,
    cleanup_audio_archives,
    enforce_play_quota,
    storage_usage,
)

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("", response_model=AppSettingsOut)
def get_settings(db: Session = Depends(get_db)) -> AppSettingsOut:
    return load_settings(db)


@router.put("", response_model=AppSettingsOut)
def put_settings(payload: AppSettingsIn, db: Session = Depends(get_db)) -> AppSettingsOut:
    data = payload.model_dump(exclude_unset=True)
    saved = save_settings(db, data)
    if "play_quota_mb" in data:
        # 改了播放缓存上限就立刻按新上限裁剪，不用等下一次播放
        enforce_play_quota(db)
    return saved


@router.post("/domain-presets", response_model=AppSettingsOut)
def create_domain_preset(payload: DomainPresetCreateIn, db: Session = Depends(get_db)) -> AppSettingsOut:
    add_preset(payload.source_id, payload.name)
    return load_settings(db)


@router.delete("/domain-presets/{preset_id}", response_model=AppSettingsOut)
def remove_domain_preset(preset_id: str, db: Session = Depends(get_db)) -> AppSettingsOut:
    try:
        delete_preset(preset_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return load_settings(db)


@router.get("/storage", response_model=StorageUsageOut)
def get_storage_usage(db: Session = Depends(get_db)) -> StorageUsageOut:
    """设置页「关于」里的存储占用：只听 DOWNLOAD_DIR 下的任务目录。"""
    return storage_usage(db)


@router.post("/storage/cleanup-audio", response_model=StorageCleanupOut)
def cleanup_storage_archives(db: Session = Depends(get_db)) -> StorageCleanupOut:
    """手动清理 opus 音频归档；清掉后重新转写会按原始地址重新抽音。"""
    return cleanup_audio_archives(db)


@router.post("/storage/archive-wav", response_model=StorageArchiveOut)
def archive_storage_wav(db: Session = Depends(get_db)) -> StorageArchiveOut:
    """把升级前遗留的 audio.wav 压成 opus 归档，一次性整理存量。"""
    return archive_existing_wavs(db)
