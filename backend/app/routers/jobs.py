from datetime import datetime, timezone
from pathlib import Path
import shutil
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import func
from sqlalchemy.orm import Query as SAQuery, Session

from app.config import settings
from app.database import get_db
from app.models import Job, stamp_job_start
from app.schemas import JobCreateIn, JobListOut, JobMediaOut, JobOut, JobUpdateIn, ResolvePreview
from app.serializers import job_out
from app.services.authctx import build_auth
from app.services.domain import job_domain_id
from app.services.ingest import resolve_media
from app.services.pipeline import get_pipeline
from app.services.media import MediaError, probe_creation_time
from app.services.playback import ensure_play_file, refresh_job_media
from app.services.cancel import clear_cancel, request_cancel
from app.services.sourcetime import file_created_at, parse_source_datetime

router = APIRouter(prefix="/api/jobs", tags=["jobs"])

JobStatusFilter = Literal["pending", "running", "done", "failed", "cancelled", "active"]


def _naive_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _title_pattern(keyword: str) -> str:
    escaped = keyword.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _jobs_query(
    db: Session,
    *,
    title: str | None,
    status: JobStatusFilter | None,
    date_from: datetime | None,
    date_to: datetime | None,
) -> SAQuery:
    query = db.query(Job)
    keyword = (title or "").strip()
    if keyword:
        query = query.filter(Job.title.ilike(_title_pattern(keyword), escape="\\"))
    if status == "active":
        query = query.filter(Job.status.in_(("pending", "running")))
    elif status:
        query = query.filter(Job.status == status)
    stamp = func.coalesce(Job.source_created_at, Job.created_at)
    if date_from is not None:
        query = query.filter(stamp >= _naive_utc(date_from))
    if date_to is not None:
        query = query.filter(stamp < _naive_utc(date_to))
    return query


def _enqueue(job_id: str) -> None:
    get_pipeline().run_job(job_id)


def _delete_job_files(job_id: str) -> None:
    root = settings.uploads_path().resolve()
    folder = (root / job_id).resolve()
    if folder == root or root not in folder.parents:
        return
    if folder.is_dir():
        shutil.rmtree(folder, ignore_errors=True)


@router.get("", response_model=JobListOut)
def list_jobs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    title: str | None = Query(None, max_length=255),
    status: JobStatusFilter | None = Query(None),
    date_from: datetime | None = Query(None),
    date_to: datetime | None = Query(None),
    db: Session = Depends(get_db),
) -> JobListOut:
    filtered = _jobs_query(db, title=title, status=status, date_from=date_from, date_to=date_to)
    total = filtered.with_entities(func.count(Job.id)).scalar() or 0
    rows = (
        _jobs_query(db, title=title, status=status, date_from=date_from, date_to=date_to)
        .order_by(Job.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return JobListOut(
        items=[job_out(row, brief=True) for row in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{job_id}", response_model=JobOut)
def get_job(job_id: str, db: Session = Depends(get_db)) -> JobOut:
    row = db.get(Job, job_id)
    if row is None:
        raise HTTPException(404, "任务不存在")
    return job_out(row)


@router.patch("/{job_id}", response_model=JobOut)
def update_job(job_id: str, payload: JobUpdateIn, db: Session = Depends(get_db)) -> JobOut:
    row = db.get(Job, job_id)
    if row is None:
        raise HTTPException(404, "任务不存在")
    row.title = payload.title.strip()
    db.commit()
    db.refresh(row)
    return job_out(row)


@router.get("/{job_id}/media", response_model=JobMediaOut)
def get_job_media(job_id: str, db: Session = Depends(get_db)) -> JobMediaOut:
    row = db.get(Job, job_id)
    if row is None:
        raise HTTPException(404, "任务不存在")
    url, refreshed, message = refresh_job_media(db, row)
    return JobMediaOut(url=url, refreshed=refreshed, message=message)


@router.get("/{job_id}/play")
def play_job_media(job_id: str, db: Session = Depends(get_db)) -> FileResponse:
    row = db.get(Job, job_id)
    if row is None:
        raise HTTPException(404, "任务不存在")
    try:
        path = ensure_play_file(db, row)
    except MediaError as exc:
        raise HTTPException(502, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(502, f"准备播放失败：{exc}") from exc
    suffix = path.suffix.lower()
    media_types = {
        ".mp4": "video/mp4",
        ".webm": "video/webm",
        ".mov": "video/quicktime",
        ".m4v": "video/mp4",
        ".ogg": "video/ogg",
        ".ogv": "video/ogg",
    }
    return FileResponse(
        path,
        media_type=media_types.get(suffix, "video/mp4"),
        filename=path.name,
        content_disposition_type="inline",
    )


@router.post("/preview", response_model=ResolvePreview)
def preview_source(payload: JobCreateIn, db: Session = Depends(get_db)) -> ResolvePreview:
    if not payload.source_url.strip() and not payload.media_url_override.strip():
        raise HTTPException(400, "请提供页面地址或媒体地址")
    auth = build_auth(
        db,
        url=payload.source_url,
        site_id=payload.site_id,
        auth_profile_id=payload.auth_profile_id,
    )
    resolved = resolve_media(payload.source_url, auth, media_url_override=payload.media_url_override)
    return ResolvePreview(
        adapter=resolved.adapter,
        title=resolved.title,
        source_type=resolved.source_type,
        media_url=resolved.media_url,
        needs_media_url=resolved.needs_media_url,
        message=resolved.message,
        extra=resolved.extra,
    )


@router.post("", response_model=JobOut)
def create_job(payload: JobCreateIn, background: BackgroundTasks, db: Session = Depends(get_db)) -> JobOut:
    if not payload.source_url.strip() and not payload.media_url_override.strip():
        raise HTTPException(400, "请提供页面地址或媒体地址")
    job = Job(
        title=payload.title,
        source_url=payload.source_url.strip(),
        site_id=payload.site_id,
        auth_profile_id=payload.auth_profile_id,
        domain_id=job_domain_id(payload.domain_id),
        media_url_override=payload.media_url_override.strip(),
        status="pending",
        stage="queued",
    )
    stamp_job_start(job)
    db.add(job)
    db.commit()
    db.refresh(job)
    background.add_task(_enqueue, job.id)
    return job_out(job)


@router.post("/upload", response_model=JobOut)
async def upload_job(
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    file: UploadFile = File(...),
    title: str = Form(""),
    source_created_at: str = Form(""),
    domain_id: str = Form(""),
) -> JobOut:
    job = Job(
        title=title or (file.filename or "本地文件"),
        source_type="local_file",
        status="pending",
        stage="queued",
        domain_id=job_domain_id(domain_id),
    )
    stamp_job_start(job)
    db.add(job)
    db.commit()
    db.refresh(job)
    folder = settings.uploads_path() / job.id
    folder.mkdir(parents=True, exist_ok=True)
    suffix = Path(file.filename or "source.bin").suffix or ".bin"
    dest = folder / f"source{suffix}"
    dest.write_bytes(await file.read())
    source_created = (
        probe_creation_time(str(dest))
        or parse_source_datetime(source_created_at)
        or file_created_at(dest)
    )
    job.source_path = str(dest)
    job.source_url = str(dest)
    job.source_created_at = source_created
    db.commit()
    db.refresh(job)
    background.add_task(_enqueue, job.id)
    return job_out(job)


@router.post("/{job_id}/resummarize", response_model=JobOut)
def resummarize_job(job_id: str, background: BackgroundTasks, db: Session = Depends(get_db)) -> JobOut:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(404, "任务不存在")
    if not job.transcript_json:
        raise HTTPException(400, "没有转写结果，无法只重跑总结")
    clear_cancel(job.id)
    stamp_job_start(job)
    job.status = "running"
    job.stage = "summarizing"
    job.error = ""
    db.commit()
    db.refresh(job)
    background.add_task(get_pipeline().resummarize_job, job.id)
    return job_out(job)


@router.post("/{job_id}/retranscribe", response_model=JobOut)
def retranscribe_job(
    job_id: str,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    continue_after: bool = Query(True, description="转写完成后是否继续校对和总结"),
) -> JobOut:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(404, "任务不存在")
    clear_cancel(job.id)
    stamp_job_start(job)
    job.status = "running"
    job.stage = "transcribing"
    job.error = ""
    job.progress = 50
    db.commit()
    db.refresh(job)
    background.add_task(get_pipeline().retranscribe_job, job.id, continue_after)
    return job_out(job)


@router.post("/{job_id}/proofread", response_model=JobOut)
def proofread_job(job_id: str, background: BackgroundTasks, db: Session = Depends(get_db)) -> JobOut:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(404, "任务不存在")
    if not job.transcript_json:
        raise HTTPException(400, "没有转写结果，无法校对")
    clear_cancel(job.id)
    stamp_job_start(job)
    job.status = "running"
    job.stage = "proofreading"
    job.error = ""
    db.commit()
    db.refresh(job)
    background.add_task(get_pipeline().proofread_job, job.id)
    return job_out(job)


@router.post("/{job_id}/cancel", response_model=JobOut)
def cancel_job(job_id: str, db: Session = Depends(get_db)) -> JobOut:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(404, "任务不存在")
    if job.status not in {"pending", "running"}:
        if job.status == "cancelled":
            return job_out(job)
        raise HTTPException(400, "当前状态不能取消")
    request_cancel(job.id)
    job.status = "cancelled"
    job.stage = "cancelled"
    job.error = "已取消"
    db.commit()
    db.refresh(job)
    return job_out(job)


@router.post("/{job_id}/retry", response_model=JobOut)
def retry_job(job_id: str, background: BackgroundTasks, db: Session = Depends(get_db)) -> JobOut:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(404, "任务不存在")
    clear_cancel(job.id)
    stamp_job_start(job)
    job.status = "pending"
    job.stage = "queued"
    job.error = ""
    job.progress = 0
    db.commit()
    db.refresh(job)
    background.add_task(_enqueue, job.id)
    return job_out(job)


@router.delete("/{job_id}")
def delete_job(job_id: str, db: Session = Depends(get_db)) -> dict:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(404, "任务不存在")
    if job.status in {"pending", "running"}:
        request_cancel(job.id)
    else:
        clear_cancel(job.id)
    _delete_job_files(job.id)
    db.delete(job)
    db.commit()
    return {"ok": True}
