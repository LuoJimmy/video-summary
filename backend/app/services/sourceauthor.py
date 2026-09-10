from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models import Job
from app.services.authctx import build_auth


def normalize_author(value: Any) -> str:
    text = str(value or "").strip()
    return text[:120]


def backfill_job_authors(db: Session) -> dict[str, list[tuple[str, str]]]:
    """为作者为空的任务按站点解析回填，解不出时再用同站点已填作者兜底。"""
    from app.services.ingest import resolve_media

    filled: list[tuple[str, str]] = []
    pending: list[Job] = []
    for job in db.query(Job).order_by(Job.created_at.asc(), Job.id.asc()).all():
        if (job.author or "").strip():
            continue
        author = _resolve_job_author(db, job, resolve_media)
        if author:
            job.author = author
            filled.append((job.id, author))
        else:
            pending.append(job)

    site_authors: dict[str, set[str]] = {}
    for job in db.query(Job).all():
        author = (job.author or "").strip()
        site_id = (job.site_id or "").strip()
        if not author or not site_id:
            continue
        site_authors.setdefault(site_id, set()).add(author)

    fallback: list[tuple[str, str]] = []
    for job in pending:
        site_id = (job.site_id or "").strip()
        names = site_authors.get(site_id) or set()
        if len(names) != 1:
            continue
        author = next(iter(names))
        job.author = author
        fallback.append((job.id, author))

    if filled or fallback:
        db.commit()
    return {"resolved": filled, "fallback": fallback}


def _resolve_job_author(db: Session, job: Job, resolve_media) -> str:
    source = (job.source_url or job.source_path or "").strip()
    if not source:
        return ""
    auth = build_auth(db, url=job.source_url, site_id=job.site_id, auth_profile_id=job.auth_profile_id)
    try:
        resolved = resolve_media(source, auth, media_url_override="")
    except Exception:
        return ""
    return normalize_author(getattr(resolved, "author", ""))
