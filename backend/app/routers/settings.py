from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import AppSettingsIn, AppSettingsOut, DomainPresetCreateIn
from app.services.domain import add_preset, delete_preset
from app.services.settings_store import load_settings, save_settings

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("", response_model=AppSettingsOut)
def get_settings(db: Session = Depends(get_db)) -> AppSettingsOut:
    return load_settings(db)


@router.put("", response_model=AppSettingsOut)
def put_settings(payload: AppSettingsIn, db: Session = Depends(get_db)) -> AppSettingsOut:
    return save_settings(db, payload.model_dump(exclude_unset=True))


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
