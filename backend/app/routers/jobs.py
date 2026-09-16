from datetime import datetime, timezone
from pathlib import Path
import shutil
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Body, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, Response
from sqlalchemy import func, or_
from sqlalchemy.orm import Query as SAQuery, Session

from app.config import settings
from app.database import get_db
from app.models import Job, stamp_job_start
from app.schemas import (
    CatalogPreviewItem,
    JobBatchActionIn,
    JobBatchActionOut,
    JobBatchFailedItem,
    JobCatalogIn,
    JobCatalogOut,
    JobCreateIn,
    JobListOut,
    JobMediaOut,
    JobOut,
    JobRetryIn,
    JobUpdateIn,
    ResolvePreview,
)
from app.serializers import job_out
from app.services.authctx import build_auth
from app.services.digest import is_digest_source
from app.services.domain import job_domain_id
from app.services.document import (
    DocumentError,
    PREVIEW_TYPES,
    office_preview_html,
    resolve_preview_file,
    webpage_preview_html,
)
from app.services.ingest.base import CatalogError, CATALOG_BATCH_LIMIT, is_document_source, local_source_type
from app.services.ingest.registry import detect_catalog, list_catalog, resolve_media
from app.services.pipeline import get_pipeline
from app.services.media import MediaError, probe_creation_time
from app.services.playback import ensure_play_file, refresh_job_media
from app.services.cancel import clear_cancel, request_cancel
from app.services.schedule import (
    _execute_jobs,
    _existing_catalog,
    catalog_item_exists,
    naive_utc,
    remember_catalog_item,
)
from app.services.sourcetime import file_created_at, parse_source_datetime

router = APIRouter(prefix="/api/jobs", tags=["jobs"])

JobStatusFilter = Literal["pending", "running", "done", "failed", "cancelled", "active"]
JobSort = Literal["source", "created", "title"]
JobOrder = Literal["asc", "desc"]


def _naive_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _like_pattern(keyword: str) -> str:
    escaped = keyword.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _jobs_order(sort: JobSort | None, order: JobOrder | None = None):
    descending = order != "asc"
    stamp = func.coalesce(Job.source_created_at, Job.created_at)

    def directed(column):
        return column.desc() if descending else column.asc()

    if sort == "created":
        return directed(Job.created_at), Job.id.desc()
    if sort == "title":
        return directed(Job.title), stamp.desc(), Job.id.desc()
    return directed(stamp), Job.created_at.desc(), Job.id.desc()


def _jobs_query(
    db: Session,
    *,
    title: str | None,
    status: JobStatusFilter | None,
    date_from: datetime | None,
    date_to: datetime | None,
    sort: JobSort | None = None,
    order: JobOrder | None = None,
) -> SAQuery:
    query = db.query(Job)
    keyword = (title or "").strip()
    if keyword:
        pattern = _like_pattern(keyword)
        query = query.filter(
            or_(
                Job.title.ilike(pattern, escape="\\"),
                Job.author.ilike(pattern, escape="\\"),
            )
        )
    if status == "active":
        query = query.filter(Job.status.in_(("pending", "running")))
    elif status:
        query = query.filter(Job.status == status)
    stamp = func.coalesce(Job.source_created_at, Job.created_at)
    if date_from is not None:
        query = query.filter(stamp >= _naive_utc(date_from))
    if date_to is not None:
        query = query.filter(stamp < _naive_utc(date_to))
    return query.order_by(*_jobs_order(sort, order))


def _enqueue(job_id: str) -> None:
    get_pipeline().run_job(job_id)


def _delete_job_files(job_id: str) -> None:
    root = settings.uploads_path().resolve()
    folder = (root / job_id).resolve()
    if folder == root or root not in folder.parents:
        return
    if folder.is_dir():
        shutil.rmtree(folder, ignore_errors=True)


def _unique_job_ids(ids: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for raw in ids:
        job_id = (raw or "").strip()
        if not job_id or job_id in seen:
            continue
        seen.add(job_id)
        unique.append(job_id)
    return unique


def _apply_cancel(job: Job) -> None:
    if job.status not in {"pending", "running"}:
        if job.status == "cancelled":
            return
        raise HTTPException(400, "当前状态不能取消")
    request_cancel(job.id)
    job.status = "cancelled"
    job.stage = "cancelled"
    job.error = "已取消"


def _apply_retry(job: Job) -> None:
    clear_cancel(job.id)
    stamp_job_start(job)
    job.status = "pending"
    job.stage = "queued"
    job.error = ""
    job.progress = 0


def _apply_delete(db: Session, job: Job) -> None:
    if job.status in {"pending", "running"}:
        request_cancel(job.id)
    else:
        clear_cancel(job.id)
    _delete_job_files(job.id)
    db.delete(job)


@router.get("", response_model=JobListOut)
def list_jobs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    title: str | None = Query(None, max_length=255),
    status: JobStatusFilter | None = Query(None),
    date_from: datetime | None = Query(None),
    date_to: datetime | None = Query(None),
    sort: JobSort = Query("source"),
    order: JobOrder = Query("desc"),
    db: Session = Depends(get_db),
) -> JobListOut:
    filtered = _jobs_query(
        db, title=title, status=status, date_from=date_from, date_to=date_to, sort=sort, order=order
    )
    total = filtered.with_entities(func.count(Job.id)).scalar() or 0
    rows = (
        _jobs_query(
            db, title=title, status=status, date_from=date_from, date_to=date_to, sort=sort, order=order
        )
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
    return job_out(row, db=db)


@router.patch("/{job_id}", response_model=JobOut)
def update_job(job_id: str, payload: JobUpdateIn, db: Session = Depends(get_db)) -> JobOut:
    row = db.get(Job, job_id)
    if row is None:
        raise HTTPException(404, "任务不存在")
    row.title = payload.title.strip()
    if payload.author is not None:
        row.author = payload.author.strip()
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


@router.get("/{job_id}/file")
def preview_job_file(
    job_id: str,
    raw: bool = Query(False),
    db: Session = Depends(get_db),
) -> Response:
    row = db.get(Job, job_id)
    if row is None:
        raise HTTPException(404, "任务不存在")
    if not is_document_source(row.source_type):
        raise HTTPException(400, "该任务不是文档，无法预览原件")
    try:
        path = resolve_preview_file(job_id, row.source_path)
    except DocumentError as exc:
        raise HTTPException(404, str(exc)) from exc
    suffix = path.suffix.lower()
    filename = path.name or f"source{suffix}"
    if not raw and suffix in {".doc", ".docx"}:
        try:
            html = office_preview_html(path)
        except Exception as exc:
            raise HTTPException(502, f"无法生成 Word 预览：{exc}") from exc
        return HTMLResponse(content=html, headers={"Content-Disposition": f'inline; filename="{path.stem}.html"'})
    if not raw and row.source_type == "web_page":
        try:
            html = webpage_preview_html(
                path,
                title=row.title,
                transcript_json=row.transcript_json,
                source_url=row.source_url or "",
            )
        except Exception as exc:
            raise HTTPException(502, f"无法生成网页预览：{exc}") from exc
        return HTMLResponse(
            content=html,
            headers={
                "Content-Disposition": f'inline; filename="{path.stem}.html"',
                "Cache-Control": "no-store",
            },
        )
    media_type = PREVIEW_TYPES.get(suffix, "application/octet-stream")
    return FileResponse(
        path,
        media_type=media_type,
        filename=filename,
        content_disposition_type="inline",
    )


def _catalog_preview(payload: JobCreateIn, db: Session) -> ResolvePreview:
    catalog = detect_catalog(payload.source_url)
    if catalog is None:
        raise HTTPException(400, "不是可展开的空间/店铺/站点地址")
    auth = build_auth(
        db,
        url=payload.source_url,
        site_id=payload.site_id,
        auth_profile_id=payload.auth_profile_id,
    )
    if catalog.adapter and (not auth.adapter or auth.adapter == "generic"):
        auth.adapter = catalog.adapter
    try:
        page = list_catalog(
            catalog.adapter,
            auth,
            catalog.catalog_id,
            cursor=payload.cursor or None,
            limit=CATALOG_BATCH_LIMIT,
        )
    except CatalogError as exc:
        raise HTTPException(400, str(exc)) from exc
    existing = _existing_catalog(db)
    items: list[CatalogPreviewItem] = []
    existing_count = 0
    for item in page.items:
        exists = catalog_item_exists(existing, item.source_url, item.title, item.created_at)
        if exists:
            existing_count += 1
        items.append(
            CatalogPreviewItem(
                source_url=item.source_url,
                title=item.title,
                author=item.author,
                created_at=item.created_at,
                exists=exists,
            )
        )
    message = page.message
    if not message and page.next_cursor:
        message = f"本批 {len(items)} 条。确认后若还有后续，会在创建区提示继续拉取。"
    elif not message:
        message = f"本批 {len(items)} 条。已存在的创建时会跳过。"
    return ResolvePreview(
        adapter=catalog.adapter,
        title=catalog.label,
        source_type="catalog",
        message=message,
        catalog=True,
        catalog_label=catalog.label,
        listed=len(items),
        existing=existing_count,
        next_cursor=page.next_cursor,
        truncated=page.truncated,
        items=items,
    )


@router.post("/preview", response_model=ResolvePreview)
def preview_source(payload: JobCreateIn, db: Session = Depends(get_db)) -> ResolvePreview:
    if not payload.source_url.strip() and not payload.media_url_override.strip():
        raise HTTPException(400, "请提供页面地址或媒体地址")
    if detect_catalog(payload.source_url) is not None:
        return _catalog_preview(payload, db)
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


@router.post("/from-catalog", response_model=JobCatalogOut)
def create_jobs_from_catalog(payload: JobCatalogIn, db: Session = Depends(get_db)) -> JobCatalogOut:
    catalog = detect_catalog(payload.source_url)
    if catalog is None:
        raise HTTPException(400, "不是可展开的空间/店铺/站点地址")
    picks: list[CatalogPreviewItem] = []
    seen: set[str] = set()
    for item in payload.items:
        url = (item.source_url or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        picks.append(item)
    if not picks:
        raise HTTPException(400, "请至少选择一条视频")
    existing = _existing_catalog(db)
    created_ids: list[str] = []
    skipped = 0
    domain_id = job_domain_id(payload.domain_id)
    author = payload.author.strip()
    for item in picks:
        url = item.source_url.strip()
        if catalog_item_exists(existing, url, item.title, item.created_at) or item.exists:
            skipped += 1
            continue
        job = Job(
            title=(item.title or "").strip() or "未命名任务",
            author=author or (item.author or "").strip(),
            source_url=url,
            site_id=payload.site_id,
            auth_profile_id=payload.auth_profile_id,
            domain_id=domain_id,
            status="pending",
            stage="queued",
            source_created_at=naive_utc(item.created_at),
        )
        stamp_job_start(job)
        db.add(job)
        db.commit()
        db.refresh(job)
        created_ids.append(job.id)
        remember_catalog_item(existing, url, item.title, item.created_at)
    if created_ids:
        _execute_jobs(created_ids)
    label = payload.catalog_label.strip() or catalog.label
    if created_ids and skipped:
        message = f"已创建 {len(created_ids)} 个任务（跳过 {skipped} 个）。"
    elif created_ids:
        message = f"已创建 {len(created_ids)} 个任务。"
    else:
        message = f"没有新任务，跳过 {skipped} 条已存在。"
    if payload.next_cursor:
        message += f"该{label}还有后续内容。"
    return JobCatalogOut(
        created=len(created_ids),
        skipped=skipped,
        next_cursor=payload.next_cursor,
        truncated=payload.truncated,
        message=message.strip(),
        catalog_label=label,
    )


@router.post("", response_model=JobOut)
def create_job(payload: JobCreateIn, background: BackgroundTasks, db: Session = Depends(get_db)) -> JobOut:
    if not payload.source_url.strip() and not payload.media_url_override.strip():
        raise HTTPException(400, "请提供页面地址或媒体地址")
    job = Job(
        title=payload.title,
        author=payload.author.strip(),
        source_url=payload.source_url.strip(),
        site_id=payload.site_id,
        auth_profile_id=payload.auth_profile_id,
        domain_id=job_domain_id(payload.domain_id),
        media_url_override=payload.media_url_override.strip(),
        summarize_document=payload.summarize_document,
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
    author: str = Form(""),
    source_created_at: str = Form(""),
    domain_id: str = Form(""),
    summarize_document: str = Form("false"),
) -> JobOut:
    suffix = Path(file.filename or "source.bin").suffix or ".bin"
    source_type = local_source_type(Path(f"source{suffix}")) if suffix else "local_file"
    job = Job(
        title=title or (file.filename or "本地文件"),
        author=author.strip(),
        source_type=source_type,
        status="pending",
        stage="queued",
        domain_id=job_domain_id(domain_id),
        summarize_document=_form_bool(summarize_document),
    )
    stamp_job_start(job)
    db.add(job)
    db.commit()
    db.refresh(job)
    folder = settings.uploads_path() / job.id
    folder.mkdir(parents=True, exist_ok=True)
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


@router.post("/batch", response_model=JobBatchActionOut)
def batch_jobs(
    payload: JobBatchActionIn,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
) -> JobBatchActionOut:
    ids = _unique_job_ids(payload.ids)
    if not ids:
        raise HTTPException(400, "请提供任务 id")
    ok: list[str] = []
    failed: list[JobBatchFailedItem] = []
    retry_ids: list[str] = []
    for job_id in ids:
        job = db.get(Job, job_id)
        if job is None:
            failed.append(JobBatchFailedItem(id=job_id, reason="任务不存在"))
            continue
        try:
            if payload.action == "cancel":
                _apply_cancel(job)
            elif payload.action == "retry":
                if job.status not in {"failed", "cancelled"}:
                    raise HTTPException(400, "当前状态不能重试")
                _apply_retry(job)
                retry_ids.append(job.id)
            else:
                _apply_delete(db, job)
        except HTTPException as exc:
            failed.append(JobBatchFailedItem(id=job_id, reason=str(exc.detail)))
            continue
        ok.append(job_id)
    db.commit()
    for job_id in retry_ids:
        background.add_task(_enqueue, job_id)
    return JobBatchActionOut(ok=ok, failed=failed)


@router.post("/{job_id}/resummarize", response_model=JobOut)
def resummarize_job(job_id: str, background: BackgroundTasks, db: Session = Depends(get_db)) -> JobOut:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(404, "任务不存在")
    if not is_digest_source(job.source_type) and not job.transcript_json:
        raise HTTPException(400, "没有转写结果，无法只重跑总结")
    clear_cancel(job.id)
    stamp_job_start(job)
    job.status = "running"
    job.stage = "summarizing"
    job.error = ""
    job.summarize_document = True
    db.commit()
    db.refresh(job)
    background.add_task(get_pipeline().resummarize_job, job.id)
    return job_out(job, db=db)


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
    if is_digest_source(job.source_type):
        raise HTTPException(400, "汇总任务不能重新转写")
    clear_cancel(job.id)
    stamp_job_start(job)
    job.status = "running"
    job.error = ""
    if is_document_source(job.source_type):
        job.stage = "extracting_text"
        job.progress = 40
    else:
        job.stage = "transcribing"
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
    if is_digest_source(job.source_type):
        raise HTTPException(400, "汇总任务不能校对转写")
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
    _apply_cancel(job)
    db.commit()
    db.refresh(job)
    return job_out(job)


@router.post("/{job_id}/retry", response_model=JobOut)
def retry_job(
    job_id: str,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    payload: JobRetryIn = Body(default_factory=JobRetryIn),
) -> JobOut:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(404, "任务不存在")
    if payload.media_url_override is not None:
        job.media_url_override = payload.media_url_override.strip()
    _apply_retry(job)
    db.commit()
    db.refresh(job)
    background.add_task(_enqueue, job.id)
    return job_out(job)


@router.delete("/{job_id}")
def delete_job(job_id: str, db: Session = Depends(get_db)) -> dict:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(404, "任务不存在")
    _apply_delete(db, job)
    db.commit()
    return {"ok": True}


def _form_bool(value: str) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}
