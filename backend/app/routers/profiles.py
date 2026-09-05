from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import AuthProfile
from app.schemas import AuthProfileIn, AuthProfileOut
from app.serializers import profile_out
from app.services.jsonutil import dumps

router = APIRouter(prefix="/api/profiles", tags=["profiles"])


@router.get("", response_model=list[AuthProfileOut])
def list_profiles(db: Session = Depends(get_db)) -> list[AuthProfileOut]:
    rows = db.query(AuthProfile).order_by(AuthProfile.created_at.asc()).all()
    return [profile_out(row) for row in rows]


@router.post("", response_model=AuthProfileOut)
def create_profile(payload: AuthProfileIn, db: Session = Depends(get_db)) -> AuthProfileOut:
    row = AuthProfile(
        name=payload.name,
        cookie=payload.cookie,
        extra_headers=dumps(payload.extra_headers),
        notes=payload.notes,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return profile_out(row)


@router.put("/{profile_id}", response_model=AuthProfileOut)
def update_profile(profile_id: str, payload: AuthProfileIn, db: Session = Depends(get_db)) -> AuthProfileOut:
    row = db.get(AuthProfile, profile_id)
    if row is None:
        raise HTTPException(404, "登录档案不存在")
    row.name = payload.name
    row.cookie = payload.cookie
    row.extra_headers = dumps(payload.extra_headers)
    row.notes = payload.notes
    db.commit()
    db.refresh(row)
    return profile_out(row)


@router.delete("/{profile_id}")
def delete_profile(profile_id: str, db: Session = Depends(get_db)) -> dict:
    row = db.get(AuthProfile, profile_id)
    if row is None:
        raise HTTPException(404, "登录档案不存在")
    db.delete(row)
    db.commit()
    return {"ok": True}
