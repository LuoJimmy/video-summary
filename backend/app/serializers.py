from sqlalchemy.orm import Session

from app.models import AuthProfile, Job, ScheduleLog, Site
from app.schemas import AuthProfileOut, JobOut, JobRelatedOut, ScheduleLogOut, ScheduleLogSiteDetail, SiteOut, SummaryResult, TranscriptSegment
from app.services.jsonutil import loads


def profile_out(row: AuthProfile) -> AuthProfileOut:
    return AuthProfileOut(
        id=row.id,
        name=row.name,
        cookie=row.cookie,
        extra_headers=loads(row.extra_headers, {}),
        notes=row.notes,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def site_out(row: Site) -> SiteOut:
    return SiteOut(
        id=row.id,
        name=row.name,
        adapter=row.adapter,
        domain_patterns=loads(row.domain_patterns, []),
        auth_profile_id=row.auth_profile_id,
        cookie_override=row.cookie_override,
        extra_headers=loads(row.extra_headers, {}),
        enabled=row.enabled,
        notes=row.notes,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def job_out(row: Job, *, brief: bool = False, db: Session | None = None) -> JobOut:
    transcript: list[TranscriptSegment] = []
    summary = None
    related: list[JobRelatedOut] = []
    if not brief:
        transcript_raw = loads(row.transcript_json, [])
        transcript = [TranscriptSegment.model_validate(item) for item in transcript_raw] if transcript_raw else []
        if row.summary_json:
            try:
                summary = SummaryResult.model_validate(loads(row.summary_json, {}))
            except Exception:
                summary = None
        if db is not None:
            from app.services.digest import related_job_refs

            related = related_job_refs(db, row)
    return JobOut(
        id=row.id,
        title=row.title,
        author=getattr(row, "author", "") or "",
        source_url=row.source_url,
        source_type=row.source_type,
        site_id=row.site_id,
        auth_profile_id=row.auth_profile_id,
        domain_id=getattr(row, "domain_id", "") or "",
        media_url=row.media_url,
        media_url_override=row.media_url_override,
        status=row.status,
        stage=row.stage,
        progress=row.progress,
        error=row.error,
        transcript=transcript,
        summary=summary,
        timing=loads(getattr(row, "timing_json", "") or "", {}),
        started_at=getattr(row, "started_at", None),
        source_created_at=getattr(row, "source_created_at", None),
        summarize_document=bool(getattr(row, "summarize_document", False)),
        schedule_log_id=getattr(row, "schedule_log_id", "") or "",
        related_jobs=related,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def schedule_log_out(row: ScheduleLog) -> ScheduleLogOut:
    raw = loads(row.detail_json, [])
    detail = []
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict):
                detail.append(ScheduleLogSiteDetail.model_validate(item))
    return ScheduleLogOut(
        id=row.id,
        started_at=row.started_at,
        finished_at=row.finished_at,
        trigger=row.trigger,
        status=row.status,
        summary=row.summary,
        detail=detail,
        digest_job_id=getattr(row, "digest_job_id", "") or "",
        rule_id=getattr(row, "rule_id", "") or "",
        rule_name=getattr(row, "rule_name", "") or "",
    )
