from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import ScheduleRuleSite, Site
from app.schemas import SiteIn, SiteOut
from app.serializers import site_out
from app.services.authctx import normalize_cookie
from app.services.jsonutil import dumps

router = APIRouter(prefix="/api/sites", tags=["sites"])


@router.get("", response_model=list[SiteOut])
def list_sites(db: Session = Depends(get_db)) -> list[SiteOut]:
    rows = db.query(Site).order_by(Site.created_at.asc()).all()
    return [site_out(row) for row in rows]


@router.post("", response_model=SiteOut)
def create_site(payload: SiteIn, db: Session = Depends(get_db)) -> SiteOut:
    row = Site(
        name=payload.name,
        adapter=payload.adapter,
        domain_patterns=dumps(payload.domain_patterns),
        auth_profile_id=payload.auth_profile_id,
        cookie_override=normalize_cookie(payload.cookie_override),
        extra_headers=dumps(payload.extra_headers),
        enabled=payload.enabled,
        notes=payload.notes,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return site_out(row)


@router.put("/{site_id}", response_model=SiteOut)
def update_site(site_id: str, payload: SiteIn, db: Session = Depends(get_db)) -> SiteOut:
    row = db.get(Site, site_id)
    if row is None:
        raise HTTPException(404, "站点不存在")
    row.name = payload.name
    row.adapter = payload.adapter
    row.domain_patterns = dumps(payload.domain_patterns)
    row.auth_profile_id = payload.auth_profile_id
    row.cookie_override = normalize_cookie(payload.cookie_override)
    row.extra_headers = dumps(payload.extra_headers)
    row.enabled = payload.enabled
    row.notes = payload.notes
    db.commit()
    db.refresh(row)
    return site_out(row)


@router.delete("/{site_id}")
def delete_site(site_id: str, db: Session = Depends(get_db)) -> dict:
    row = db.get(Site, site_id)
    if row is None:
        raise HTTPException(404, "站点不存在")
    extra = db.query(ScheduleRuleSite).filter(ScheduleRuleSite.site_id == site_id).delete()
    if extra:
        db.flush()
    if row.adapter != "generic":
        remain = db.query(Site).filter(Site.adapter == row.adapter, Site.id != site_id).count()
        if remain <= 0:
            labels = {"xiaoe": "小鹅通", "yueniu": "约牛", "bilibili": "B站"}
            raise HTTPException(400, f"至少保留一个{labels.get(row.adapter, row.adapter)}站点")
    db.delete(row)
    db.commit()
    return {"ok": True}
