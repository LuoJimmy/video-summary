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
DIGEST_RETRY_PROMPT = (
    "上次输出不是合法 JSON，或 overview 没写完。请重新输出完整可解析的 JSON：只要 title 和 overview。"
    "overview 必须含写满的「一句话总结」、主题与核心观点表三行、「论证结构」（按主题合并，禁止按来源拆章）以及「辨立场」。"
    "关键判断旁注明来源作者。禁止片子时钟。不要输出 chapters 或 key_points。"
)


def is_digest_source(source_type: str | None) -> bool:
    return (source_type or "") == DIGEST_SOURCE


def source_jobs_for_log(db: Session, log_id: str) -> list[Job]:
    return (
        db.query(Job)
        .filter(Job.schedule_log_id == log_id)
        .filter(Job.source_type != DIGEST_SOURCE)
        .order_by(Job.created_at.asc(), Job.id.asc())
        .all()
    )


def related_job_refs(db: Session, job: Job) -> list[JobRelatedOut]:
    log_id = (getattr(job, "schedule_log_id", "") or "").strip()
    if not is_digest_source(job.source_type) or not log_id:
        return []
    return [
        JobRelatedOut(
            id=row.id,
            title=row.title or "未命名任务",
            author=row.author or "",
            status=row.status,
        )
        for row in source_jobs_for_log(db, log_id)
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


def digest_job_title(started_at) -> str:
    stamp = ensure_utc(started_at or utcnow()).astimezone(SHANGHAI)
    return stamp.strftime("%Y-%m-%d %H:%M") + " 定时汇总"


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


def fill_digest_job(db: Session, job: Job) -> None:
    log_id = (getattr(job, "schedule_log_id", "") or "").strip()
    if not log_id:
        raise SummarizeError("没有对应的定时运行，无法汇总")
    sources = digest_sources(source_jobs_for_log(db, log_id))
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
