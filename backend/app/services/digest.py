from __future__ import annotations

import json
import re

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import Job, ScheduleLog, stamp_job_start, utcnow
from app.schemas import AppSettingsOut, JobRelatedOut, SummaryResult
from app.services.cancel import JobCancelled, job_scope, raise_if_cancelled
from app.services.domain import digest_prompt, job_domain_id, job_pack_scope
from app.services.httpclient import create_chat_completion, openai_client
from app.services.jsonutil import coerce_model_text, loads, parse_model_json
from app.services.settings_store import load_settings
from app.services.sourcetime import SHANGHAI, ensure_utc
from app.services.summarize import (
    SummarizeError,
    extract_overview_document,
    overview_is_incomplete,
    title_from_overview,
    title_is_blank,
)

DIGEST_SOURCE = "schedule_digest"
MANUAL_DIGEST_SOURCE = "digest"
DIGEST_SOURCE_TYPES = (DIGEST_SOURCE, MANUAL_DIGEST_SOURCE)
DIGEST_URL_PREFIX = "digest://"
DIGEST_RETRY_PROMPT = (
    "上次输出不是合法 JSON，或 overview 没写完。请重新输出完整可解析的 JSON：只要 title 和 overview。"
    "overview 必须含写满的「一句话总结」、主题与核心观点表三行、「论证结构」（按主题合并，禁止按来源拆章）以及「辨立场」。"
    "关键判断旁注明来源作者。禁止片子时钟。不要输出 chapters 或 key_points。"
)


def is_digest_source(source_type: str | None) -> bool:
    return (source_type or "") in DIGEST_SOURCE_TYPES


def encode_digest_source_url(job_ids: list[str]) -> str:
    return DIGEST_URL_PREFIX + ",".join(job_ids)


def parse_digest_source_ids(source_url: str | None) -> list[str]:
    raw = (source_url or "").strip()
    if not raw.startswith(DIGEST_URL_PREFIX):
        return []
    seen: set[str] = set()
    ids: list[str] = []
    for part in raw[len(DIGEST_URL_PREFIX) :].split(","):
        job_id = part.strip()
        if not job_id or job_id in seen:
            continue
        seen.add(job_id)
        ids.append(job_id)
    return ids


def source_jobs_for_log(db: Session, log_id: str) -> list[Job]:
    return (
        db.query(Job)
        .filter(Job.schedule_log_id == log_id)
        .filter(~Job.source_type.in_(DIGEST_SOURCE_TYPES))
        .order_by(Job.created_at.asc(), Job.id.asc())
        .all()
    )


def source_jobs_for_digest(db: Session, job: Job) -> list[Job]:
    if not is_digest_source(job.source_type):
        return []
    log_id = (getattr(job, "schedule_log_id", "") or "").strip()
    if log_id:
        return source_jobs_for_log(db, log_id)
    ids = parse_digest_source_ids(job.source_url)
    if not ids:
        return []
    rows = {
        row.id: row
        for row in db.query(Job).filter(Job.id.in_(ids)).filter(~Job.source_type.in_(DIGEST_SOURCE_TYPES)).all()
    }
    return [rows[job_id] for job_id in ids if job_id in rows]


def related_job_refs(db: Session, job: Job) -> list[JobRelatedOut]:
    if not is_digest_source(job.source_type):
        return []
    return [
        JobRelatedOut(
            id=row.id,
            title=row.title or "未命名任务",
            author=row.author or "",
            status=row.status,
        )
        for row in source_jobs_for_digest(db, job)
    ]


def digest_sources(jobs: list[Job]) -> list[dict]:
    sources: list[dict] = []
    for job in jobs:
        if job.status != "done" or not (job.summary_json or "").strip():
            continue
        summary = loads(job.summary_json, {})
        if not isinstance(summary, dict):
            continue
        chapters: list[dict] = []
        for raw in summary.get("chapters") or []:
            if not isinstance(raw, dict):
                continue
            title = str(raw.get("title") or "").strip()
            bullets = [str(item).strip() for item in (raw.get("bullets") or []) if str(item).strip()]
            if title or bullets:
                chapters.append({"title": title, "bullets": bullets})
        if not chapters:
            continue
        sources.append({"author": (job.author or "").strip(), "chapters": chapters})
    return sources


def digest_job_title(started_at, scheduled: bool = True) -> str:
    stamp = ensure_utc(started_at or utcnow()).astimezone(SHANGHAI)
    suffix = "定时汇总" if scheduled else "汇总"
    return stamp.strftime("%Y-%m-%d %H:%M") + " " + suffix


def digest_payload_keys(sources: list[dict]) -> set[str]:
    keys: set[str] = set()
    for item in sources:
        keys.update(item.keys())
        for chapter in item.get("chapters") or []:
            if isinstance(chapter, dict):
                keys.update(chapter.keys())
    return keys


def summarize_digest(sources: list[dict], settings: AppSettingsOut) -> SummaryResult:
    if not settings.summarize_api_key:
        raise SummarizeError("未配置总结 API Key")
    if not sources:
        raise SummarizeError("没有可用的总结，无法汇总")
    client = openai_client(settings.summarize_api_key, settings.summarize_base_url)
    user_content = json.dumps(sources, ensure_ascii=False)
    system = digest_prompt()
    payload = _complete_digest(client, settings, system, user_content)
    title = (payload.get("title") or "").strip()
    overview = extract_overview_document(str(payload.get("overview") or ""))
    if title_is_blank(title):
        title = title_from_overview(overview) or "定时汇总"
    if overview_is_incomplete(overview):
        raise SummarizeError("综述未写完")
    return SummaryResult(title=title, overview=overview, chapters=[], key_points=[])


def _complete_digest(client, settings: AppSettingsOut, system: str, user_content: str) -> dict:
    content = _chat(client, settings, system, user_content)
    parsed = _parse_digest(content)
    if parsed is not None:
        return parsed
    content = _chat(client, settings, system, f"{user_content}\n\n{DIGEST_RETRY_PROMPT}")
    parsed = _parse_digest(content)
    if parsed is not None:
        return parsed
    preview = re.sub(r"\s+", " ", (content or "")[:80]).strip()
    hint = f"；原文开头：{preview}" if preview else ""
    raise SummarizeError(f"汇总结果不是合法 JSON{hint}")


def _parse_digest(content: str) -> dict | None:
    try:
        payload = parse_model_json(content)
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    overview = extract_overview_document(str(payload.get("overview") or ""))
    if overview_is_incomplete(overview):
        return None
    return {"title": str(payload.get("title") or ""), "overview": overview}


def _chat(client, settings: AppSettingsOut, system: str, user_content: str) -> str:
    kwargs: dict = {
        "model": settings.summarize_model or "deepseek-v4-flash",
        "temperature": 0.2,
        "max_tokens": 8192,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user_content},
        ],
        "response_format": {"type": "json_object"},
    }
    try:
        response = create_chat_completion(client, **kwargs)
    except JobCancelled:
        raise
    except Exception as exc:
        raise SummarizeError(f"总结接口调用失败：{exc}") from exc
    message = response.choices[0].message
    text = coerce_model_text(getattr(message, "content", None))
    if text:
        return text
    return coerce_model_text(getattr(message, "reasoning_content", None))


def create_digest_from_jobs(db: Session, job_ids: list[str]) -> Job:
    seen: set[str] = set()
    ids: list[str] = []
    for raw in job_ids:
        job_id = (raw or "").strip()
        if not job_id or job_id in seen:
            continue
        seen.add(job_id)
        ids.append(job_id)
    if len(ids) < 2:
        raise ValueError("请至少选择 2 个任务")
    rows: list[Job] = []
    for job_id in ids:
        job = db.get(Job, job_id)
        if job is None:
            raise ValueError("任务不存在")
        if is_digest_source(job.source_type):
            continue
        rows.append(job)
    usable = [job for job in rows if digest_sources([job])]
    if len(usable) < 2:
        raise ValueError("至少需要 2 个已完成且有章节总结的任务")
    domain_id = job_domain_id(next((job.domain_id for job in usable if job.domain_id), ""))
    digest = Job(
        title=digest_job_title(utcnow(), scheduled=False),
        author="",
        source_url=encode_digest_source_url([job.id for job in usable]),
        source_type=MANUAL_DIGEST_SOURCE,
        domain_id=domain_id,
        status="running",
        stage="summarizing",
        progress=80,
    )
    stamp_job_start(digest)
    db.add(digest)
    db.commit()
    db.refresh(digest)
    return digest


def fill_digest_job(db: Session, job: Job) -> None:
    sources = digest_sources(source_jobs_for_digest(db, job))
    if not sources:
        raise SummarizeError("没有可用的总结，无法汇总")
    raise_if_cancelled(job.id)
    summary = summarize_digest(sources, load_settings(db))
    raise_if_cancelled(job.id)
    job.summary_json = summary.model_dump_json()
    job.status = "done"
    job.stage = "done"
    job.progress = 100
    job.error = ""
    db.add(job)
    db.commit()
    db.refresh(job)


def _ensure_digest_job(db: Session, log: ScheduleLog, domain_id: str) -> Job:
    job = db.get(Job, log.digest_job_id) if log.digest_job_id else None
    if job is None:
        job = Job(
            title=digest_job_title(log.started_at),
            author="",
            source_url=f"schedule://{log.id}",
            source_type=DIGEST_SOURCE,
            domain_id=domain_id,
            schedule_log_id=log.id,
            status="running",
            stage="summarizing",
            progress=80,
        )
        stamp_job_start(job)
        db.add(job)
        db.commit()
        db.refresh(job)
        log.digest_job_id = job.id
        db.add(log)
        db.commit()
        return job
    stamp_job_start(job)
    job.status = "running"
    job.stage = "summarizing"
    job.progress = 80
    job.error = ""
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def _fail_digest_job(db: Session, job: Job | None, message: str) -> None:
    if job is None or job.status == "cancelled":
        return
    job.status = "failed"
    job.error = message
    db.add(job)
    db.commit()


def run_schedule_digest(log_id: str) -> None:
    db = SessionLocal()
    job: Job | None = None
    try:
        log = db.get(ScheduleLog, log_id)
        if log is None:
            return
        source_jobs = source_jobs_for_log(db, log_id)
        if not digest_sources(source_jobs):
            return
        domain_id = job_domain_id(next((row.domain_id for row in source_jobs if row.domain_id), ""))
        job = _ensure_digest_job(db, log, domain_id)
        with job_scope(job.id), job_pack_scope(job.domain_id):
            fill_digest_job(db, job)
    except JobCancelled:
        if job is not None and job.status not in {"cancelled", "done"}:
            job.status = "cancelled"
            job.stage = "cancelled"
            job.error = "已取消"
            db.add(job)
            db.commit()
    except (SummarizeError, RuntimeError) as exc:
        _fail_digest_job(db, job, str(exc))
    except Exception as exc:
        _fail_digest_job(db, job, f"未预期错误：{exc}")
    finally:
        db.close()
