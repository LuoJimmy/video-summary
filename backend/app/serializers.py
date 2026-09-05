from app.models import AuthProfile, Job, Site
from app.schemas import AuthProfileOut, JobOut, SiteOut, SummaryResult, TranscriptSegment
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


def job_out(row: Job, *, brief: bool = False) -> JobOut:
    transcript: list[TranscriptSegment] = []
    summary = None
    if not brief:
        transcript_raw = loads(row.transcript_json, [])
        transcript = [TranscriptSegment.model_validate(item) for item in transcript_raw] if transcript_raw else []
        if row.summary_json:
            try:
                summary = SummaryResult.model_validate(loads(row.summary_json, {}))
            except Exception:
                summary = None
    return JobOut(
        id=row.id,
        title=row.title,
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
        created_at=row.created_at,
        updated_at=row.updated_at,
    )
