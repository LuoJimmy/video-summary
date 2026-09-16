from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import AppSetting, Job, ScheduleLog, ScheduleSite, Site, stamp_job_start, utcnow
from app.schemas import ScheduleIn, ScheduleLogOut, ScheduleOut, ScheduleSiteOut
from app.serializers import schedule_log_out
from app.services.authctx import build_auth
from app.services.domain import job_domain_id
from app.services.ingest.base import CatalogError, CatalogItem
from app.services.ingest.bilibili import is_bili_rate_limited
from app.services.ingest.registry import list_catalog
from app.services.ingest.xiaoe import XIAOE_HOSTS, parse_xiaoe_ref
from app.services.jsonutil import dumps
from app.services.pipeline import get_pipeline
from app.services.settings_store import parse_flag
from app.services.sourcetime import SHANGHAI, ensure_utc

SCHEDULE_ADAPTERS = ("xiaoe", "yueniu", "bilibili")
CATALOG_HINTS = {
    "xiaoe": "店铺 app_id 或 H5 地址，多个用逗号/换行分隔",
    "yueniu": "可空；填写则按作者 authorId 过滤，多个用逗号分隔",
    "bilibili": "UP 的 mid 或空间页，多个用逗号/换行分隔",
}
DEFAULT_TIME = "08:00"
DEFAULT_MAX_JOBS = 5
MAX_JOBS_LIMIT = 20
BILI_CATALOG_PAUSE = 2.0
DISABLED_WAIT = 3600.0
BILI_RATE_LIMIT_KEEP = "后续稿件列表被限流，已保留已拉到的条目。请等几分钟再试，或到站点页填写 Cookie 保持登录态"

_stop = threading.Event()
_wake = threading.Event()
_run_lock = threading.Lock()
_exec_lock = threading.Lock()
_thread: threading.Thread | None = None
_startup_checked = False


def _setting(db: Session, key: str, default: str = "") -> str:
    row = db.get(AppSetting, key)
    return row.value if row else default


def _put_setting(db: Session, key: str, value: str) -> None:
    row = db.get(AppSetting, key)
    if row is None:
        db.add(AppSetting(key=key, value=value))
    else:
        row.value = value


def parse_hhmm(value: str) -> tuple[int, int]:
    text = (value or "").strip()
    match = re.fullmatch(r"(\d{1,2}):(\d{2})", text)
    if not match:
        raise ValueError("定时时间格式应为 HH:MM")
    hour, minute = int(match.group(1)), int(match.group(2))
    if hour > 23 or minute > 59:
        raise ValueError("定时时间格式应为 HH:MM")
    return hour, minute


def format_hhmm(hour: int, minute: int) -> str:
    return f"{hour:02d}:{minute:02d}"


def parse_since_date(value: str) -> datetime | None:
    text = (value or "").strip()
    if not text:
        return None
    try:
        local = datetime.strptime(text, "%Y-%m-%d").replace(tzinfo=SHANGHAI)
    except ValueError as exc:
        raise ValueError("起始日期格式应为 YYYY-MM-DD") from exc
    return local.astimezone(timezone.utc)


def shanghai_today_start(now: datetime | None = None) -> datetime:
    local = (now or datetime.now(tz=SHANGHAI)).astimezone(SHANGHAI)
    return local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)


def effective_schedule_since(since_text: str, now: datetime | None = None) -> datetime:
    """定时扫描的下限：默认当天 0 点；配置更早则仍只拉当天，更晚则等到那一天。"""
    today = shanghai_today_start(now)
    configured = parse_since_date(since_text) if (since_text or "").strip() else None
    if configured is None:
        return today
    stamp = ensure_utc(configured)
    return stamp if stamp > today else today


def _schedule_site_error(
    error: str,
    *,
    created: int,
    listed: int,
    skipped: int,
    quota_filled: bool,
) -> str:
    text = (error or "").strip()
    if not text or not is_bili_rate_limited(message=text):
        return text
    if quota_filled:
        return ""
    if created or listed or skipped:
        return BILI_RATE_LIMIT_KEEP
    return text


def parse_max_jobs(value: object, default: int = DEFAULT_MAX_JOBS) -> int:
    try:
        number = int(str(value).strip() or default)
    except (TypeError, ValueError):
        number = default
    return max(1, min(number, MAX_JOBS_LIMIT))


def split_catalog_ids(catalog_id: str) -> list[str]:
    parts = re.split(r"[\s,;，；]+", (catalog_id or "").strip())
    seen: list[str] = []
    for part in parts:
        text = part.strip()
        if text and text not in seen:
            seen.append(text)
    return seen


def normalize_source_url(url: str) -> str:
    raw = (url or "").strip()
    if not raw:
        return ""
    parsed = urlparse(raw)
    scheme = (parsed.scheme or "https").lower()
    host = (parsed.hostname or "").lower()
    if not host and parsed.path:
        return raw.rstrip("/")
    path = parsed.path.rstrip("/")
    query = parsed.query
    netloc = host
    if parsed.port and parsed.port not in (80, 443):
        netloc = f"{host}:{parsed.port}"
    if query:
        return f"{scheme}://{netloc}{path}?{query}"
    return f"{scheme}://{netloc}{path}"


def naive_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return ensure_utc(value).replace(tzinfo=None)


def _schedulable_sites(db: Session) -> list[Site]:
    rows = (
        db.query(Site)
        .filter(Site.adapter.in_(SCHEDULE_ADAPTERS))
        .order_by(Site.created_at.asc(), Site.id.asc())
        .all()
    )
    return rows


def load_schedule(db: Session) -> ScheduleOut:
    try:
        hour, minute = parse_hhmm(_setting(db, "schedule_time", DEFAULT_TIME))
        time_text = format_hhmm(hour, minute)
    except ValueError:
        time_text = DEFAULT_TIME
    since = _setting(db, "schedule_since", "")
    domain_id = _setting(db, "schedule_domain_id", "") or job_domain_id("")
    configs = {row.site_id: row for row in db.query(ScheduleSite).all()}
    sites: list[ScheduleSiteOut] = []
    for site in _schedulable_sites(db):
        row = configs.get(site.id)
        sites.append(
            ScheduleSiteOut(
                site_id=site.id,
                name=site.name,
                adapter=site.adapter,
                enabled=bool(row.enabled) if row else False,
                catalog_id=(row.catalog_id if row else "") or "",
                catalog_hint=CATALOG_HINTS.get(site.adapter, ""),
            )
        )
    return ScheduleOut(
        enabled=parse_flag(_setting(db, "schedule_enabled", "0"), False),
        time=time_text,
        since=since,
        max_jobs=parse_max_jobs(_setting(db, "schedule_max_jobs", str(DEFAULT_MAX_JOBS))),
        domain_id=domain_id,
        digest_enabled=parse_flag(_setting(db, "schedule_digest_enabled", "1"), True),
        sites=sites,
    )


def save_schedule(db: Session, payload: ScheduleIn) -> ScheduleOut:
    hour, minute = parse_hhmm(payload.time)
    since = (payload.since or "").strip()
    if since:
        parse_since_date(since)
    known = {site.id: site for site in _schedulable_sites(db)}
    for item in payload.sites:
        site = known.get(item.site_id)
        if site is None:
            raise ValueError("只能为小鹅通、约牛或 B 站配置定时任务")
        catalog_id = (item.catalog_id or "").strip()
        ids = split_catalog_ids(catalog_id)
        if item.enabled and site.adapter in {"xiaoe", "bilibili"} and not ids:
            label = "小鹅通店铺 app_id" if site.adapter == "xiaoe" else "B 站 UP 的 mid"
            raise ValueError(f"{site.name} 已启用定时，请填写{label}，多个可用逗号分隔")
        row = db.get(ScheduleSite, item.site_id)
        if row is None:
            row = ScheduleSite(site_id=item.site_id)
            db.add(row)
        row.enabled = bool(item.enabled)
        row.catalog_id = catalog_id
    _put_setting(db, "schedule_enabled", "1" if payload.enabled else "0")
    _put_setting(db, "schedule_time", format_hhmm(hour, minute))
    _put_setting(db, "schedule_since", since)
    _put_setting(db, "schedule_max_jobs", str(parse_max_jobs(payload.max_jobs)))
    _put_setting(db, "schedule_domain_id", (payload.domain_id or "").strip())
    _put_setting(db, "schedule_digest_enabled", "1" if payload.digest_enabled else "0")
    db.commit()
    wake_scheduler()
    return load_schedule(db)


def list_logs(db: Session, limit: int = 20) -> list:
    size = max(1, min(int(limit or 20), 50))
    rows = db.query(ScheduleLog).order_by(ScheduleLog.started_at.desc(), ScheduleLog.id.desc()).limit(size).all()
    return [schedule_log_out(row) for row in rows]


def clear_logs(db: Session) -> dict:
    db.query(ScheduleLog).delete()
    db.commit()
    return {"ok": True}


@dataclass
class CatalogExistsIndex:
    urls: set[str] = field(default_factory=set)
    xiaoe_ids: set[str] = field(default_factory=set)
    xiaoe_title_days: set[tuple[str, str]] = field(default_factory=set)
    xiaoe_title_counts: dict[str, int] = field(default_factory=dict)


def _xiaoe_host(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    if not host:
        return False
    return any(host == domain or host.endswith("." + domain) for domain in XIAOE_HOSTS)


def _title_key(title: str) -> str:
    text = re.sub(r"\s+", "", (title or "").strip().lower())
    return re.sub(r"^\d{1,2}\.\d{1,2}", "", text)


def _shanghai_day(value: datetime | None) -> str:
    if value is None:
        return ""
    stamp = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    return stamp.astimezone(SHANGHAI).strftime("%Y-%m-%d")


def remember_catalog_item(
    index: CatalogExistsIndex,
    url: str,
    title: str = "",
    created_at: datetime | None = None,
) -> None:
    raw = (url or "").strip()
    if raw:
        index.urls.add(raw)
        normalized = normalize_source_url(raw)
        if normalized:
            index.urls.add(normalized)
        _, resource_id = parse_xiaoe_ref(raw)
        if resource_id:
            index.xiaoe_ids.add(resource_id.lower())
    if not raw or not _xiaoe_host(raw):
        return
    key = _title_key(title)
    if not key:
        return
    index.xiaoe_title_counts[key] = index.xiaoe_title_counts.get(key, 0) + 1
    day = _shanghai_day(created_at)
    if day:
        index.xiaoe_title_days.add((key, day))


def catalog_item_exists(
    index: CatalogExistsIndex,
    url: str,
    title: str = "",
    created_at: datetime | None = None,
) -> bool:
    raw = (url or "").strip()
    if not raw:
        return False
    if raw in index.urls:
        return True
    normalized = normalize_source_url(raw)
    if normalized and normalized in index.urls:
        return True
    _, resource_id = parse_xiaoe_ref(raw)
    if resource_id and resource_id.lower() in index.xiaoe_ids:
        return True
    if not _xiaoe_host(raw):
        return False
    key = _title_key(title)
    if not key:
        return False
    day = _shanghai_day(created_at)
    if day and (key, day) in index.xiaoe_title_days:
        return True
    if not day and index.xiaoe_title_counts.get(key, 0) == 1:
        return True
    return False


def _existing_catalog(db: Session) -> CatalogExistsIndex:
    index = CatalogExistsIndex()
    for url, title, source_created_at in db.query(Job.source_url, Job.title, Job.source_created_at).all():
        remember_catalog_item(index, url or "", title or "", source_created_at)
    return index


def _existing_urls(db: Session) -> set[str]:
    return _existing_catalog(db).urls


def _sort_items(items: list[CatalogItem]) -> list[CatalogItem]:
    def key(item: CatalogItem) -> tuple:
        stamp = naive_utc(item.created_at) or datetime.min
        return (stamp, item.source_url)

    return sorted(items, key=key, reverse=True)


def _join_unique(messages: list[str]) -> str:
    seen: list[str] = []
    for raw in messages:
        text = (raw or "").strip()
        if text and text not in seen:
            seen.append(text)
    return "；".join(seen)


def _build_summary(details: list[dict], created_total: int, skipped_total: int) -> tuple[str, str]:
    errors = [item for item in details if item.get("error")]
    parts: list[str] = []
    for item in details:
        name = item.get("site_name") or "站点"
        if item.get("error") and not item.get("created") and not item.get("skipped") and not item.get("listed"):
            parts.append(f"{name}：失败 {item['error']}")
            continue
        bits = []
        if item.get("created"):
            bits.append(f"新建 {item['created']}")
        if item.get("skipped"):
            bits.append(f"跳过 {item['skipped']}")
        if item.get("error"):
            bits.append(item["error"])
        if not bits:
            bits.append("无新内容")
        parts.append(f"{name}：{'，'.join(bits)}")
    if not details:
        text = "没有启用的定时站点"
        return text, "ok"
    text = "；".join(parts)
    has_progress = created_total > 0 or skipped_total > 0 or any(item.get("listed") for item in details)
    if errors and len(errors) == len(details) and not has_progress:
        return text, "failed"
    if errors:
        return text, "partial"
    if created_total == 0 and skipped_total == 0:
        return text or "无新内容", "ok"
    return text, "ok"


def run_once(trigger: str = "cron", execute: bool = True, db: Session | None = None) -> ScheduleLogOut:
    own_session = db is None
    if db is None:
        db = SessionLocal()
    created_ids: list[str] = []
    digest_log_id: str | None = None
    try:
        with _run_lock:
            cfg = load_schedule(db)
            if trigger != "manual" and not cfg.enabled:
                raise ValueError("定时任务未启用")
            if trigger != "manual" and not missed_scheduled_run(db):
                hour, minute = parse_hhmm(cfg.time)
                local = datetime.now().astimezone()
                scheduled_today = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
                if local < scheduled_today:
                    raise ValueError("未到今天的定时时间")
                raise ValueError("今日已执行过定时任务")
            since = effective_schedule_since(cfg.since)
            today = _shanghai_day(datetime.now(tz=SHANGHAI))
            remaining = cfg.max_jobs
            domain_id = job_domain_id(cfg.domain_id)
            existing = _existing_catalog(db)
            log = ScheduleLog(trigger=trigger, status="running", summary="正在扫描站点")
            db.add(log)
            db.commit()
            db.refresh(log)

            details: list[dict] = []
            created_total = 0
            skipped_total = 0
            configs = {row.site_id: row for row in db.query(ScheduleSite).all()}
            quota_left = remaining > 0
            for site in _schedulable_sites(db):
                row = configs.get(site.id)
                if row is None or not row.enabled or not site.enabled:
                    continue
                detail = {
                    "site_id": site.id,
                    "site_name": site.name,
                    "listed": 0,
                    "created": 0,
                    "skipped": 0,
                    "error": "",
                }
                if not quota_left:
                    continue
                auth = build_auth(db, site_id=site.id, auth_profile_id=site.auth_profile_id)
                items: list[CatalogItem] = []
                errors: list[str] = []
                catalog_ids = split_catalog_ids(row.catalog_id)
                if not catalog_ids:
                    catalog_ids = [""]
                for index, catalog_id in enumerate(catalog_ids):
                    if index and site.adapter == "bilibili" and BILI_CATALOG_PAUSE:
                        time.sleep(BILI_CATALOG_PAUSE)
                    try:
                        page = list_catalog(site.adapter, auth, catalog_id, since=since)
                        items.extend(page)
                        note = str(getattr(page, "message", "") or "").strip()
                        if note:
                            errors.append(note)
                            if site.adapter == "bilibili" and is_bili_rate_limited(message=note):
                                break
                    except CatalogError as exc:
                        errors.append(str(exc))
                        if site.adapter == "bilibili" and is_bili_rate_limited(message=str(exc)):
                            break
                    except Exception as exc:
                        errors.append(str(exc))
                if not items and errors:
                    detail["error"] = _schedule_site_error(
                        _join_unique(errors),
                        created=0,
                        listed=0,
                        skipped=0,
                        quota_filled=remaining <= 0,
                    )
                    details.append(detail)
                    continue
                ranked = _sort_items(items)
                detail["listed"] = len(ranked)
                for item in ranked:
                    url = (item.source_url or "").strip()
                    if not url:
                        continue
                    if item.created_at is None or _shanghai_day(item.created_at) != today:
                        continue
                    if ensure_utc(item.created_at) < ensure_utc(since):
                        continue
                    if catalog_item_exists(existing, url, item.title, item.created_at):
                        detail["skipped"] += 1
                        skipped_total += 1
                        continue
                    if remaining <= 0:
                        quota_left = False
                        break
                    job = Job(
                        title=(item.title or "").strip() or "未命名任务",
                        author=(item.author or "").strip(),
                        source_url=url,
                        site_id=site.id,
                        auth_profile_id=site.auth_profile_id,
                        domain_id=domain_id,
                        status="pending",
                        stage="queued",
                        source_created_at=naive_utc(item.created_at),
                        schedule_log_id=log.id,
                    )
                    stamp_job_start(job)
                    db.add(job)
                    db.commit()
                    db.refresh(job)
                    created_ids.append(job.id)
                    remember_catalog_item(existing, url, item.title, item.created_at)
                    remaining -= 1
                    detail["created"] += 1
                    created_total += 1
                    if remaining <= 0:
                        quota_left = False
                detail["error"] = _schedule_site_error(
                    _join_unique(errors) if errors else "",
                    created=detail["created"],
                    listed=detail["listed"],
                    skipped=detail["skipped"],
                    quota_filled=remaining <= 0,
                )
                details.append(detail)

            summary, status = _build_summary(details, created_total, skipped_total)
            log.finished_at = utcnow()
            log.status = status
            log.summary = summary
            log.detail_json = dumps(details)
            db.commit()
            db.refresh(log)
            result = schedule_log_out(log)
            if cfg.digest_enabled:
                digest_log_id = log.id
    finally:
        if own_session:
            db.close()
    if execute:
        _execute_jobs(created_ids, digest_log_id=digest_log_id)
    return result


def _run_created_jobs(job_ids: list[str], digest_log_id: str | None = None) -> None:
    for job_id in job_ids:
        try:
            get_pipeline().run_job(job_id)
        except Exception:
            continue
    if digest_log_id:
        try:
            from app.services.digest import run_schedule_digest

            run_schedule_digest(digest_log_id)
        except Exception:
            return


def _execute_jobs(job_ids: list[str], digest_log_id: str | None = None) -> None:
    if not job_ids:
        return

    def worker() -> None:
        with _exec_lock:
            _run_created_jobs(job_ids, digest_log_id=digest_log_id)

    thread = threading.Thread(target=worker, name="schedule-exec", daemon=True)
    thread.start()


def seconds_until_tick(enabled: bool, time_text: str, now: datetime | None = None) -> float:
    if not enabled:
        return DISABLED_WAIT
    hour, minute = parse_hhmm(time_text or DEFAULT_TIME)
    local = (now or datetime.now().astimezone()).astimezone()
    target = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= local:
        target += timedelta(days=1)
    return max(1.0, (target - local).total_seconds())


def missed_scheduled_run(db: Session, now: datetime | None = None) -> bool:
    cfg = load_schedule(db)
    if not cfg.enabled:
        return False
    hour, minute = parse_hhmm(cfg.time)
    local = (now or datetime.now().astimezone()).astimezone()
    scheduled_today = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if local < scheduled_today:
        return False
    start_local = local.replace(hour=0, minute=0, second=0, microsecond=0)
    start_utc = start_local.astimezone(timezone.utc).replace(tzinfo=None)
    row = (
        db.query(ScheduleLog)
        .filter(ScheduleLog.finished_at.isnot(None))
        .filter(ScheduleLog.started_at >= start_utc)
        .first()
    )
    return row is None


def wake_scheduler() -> None:
    _wake.set()


def start_scheduler() -> None:
    global _thread, _startup_checked
    if _thread is not None and _thread.is_alive():
        return
    _stop.clear()
    _wake.clear()
    _startup_checked = False
    _thread = threading.Thread(target=_loop, name="schedule", daemon=True)
    _thread.start()


def stop_scheduler() -> None:
    _stop.set()
    _wake.set()
    thread = _thread
    if thread is not None and thread.is_alive():
        thread.join(timeout=2)


def _safe_run_once(trigger: str) -> None:
    try:
        run_once(trigger)
    except Exception:
        return


def start_detached_run(trigger: str = "manual") -> ScheduleLogOut:
    db = SessionLocal()
    try:
        running = (
            db.query(ScheduleLog)
            .filter(ScheduleLog.finished_at.is_(None))
            .order_by(ScheduleLog.started_at.desc(), ScheduleLog.id.desc())
            .first()
        )
        if running is not None:
            return schedule_log_out(running)
        previous = (
            db.query(ScheduleLog)
            .order_by(ScheduleLog.started_at.desc(), ScheduleLog.id.desc())
            .first()
        )
        previous_id = previous.id if previous else ""
    finally:
        db.close()

    thread = threading.Thread(target=_safe_run_once, args=(trigger,), name="schedule-run", daemon=True)
    thread.start()
    deadline = time.time() + 5.0
    while time.time() < deadline:
        db = SessionLocal()
        try:
            running = (
                db.query(ScheduleLog)
                .filter(ScheduleLog.finished_at.is_(None))
                .order_by(ScheduleLog.started_at.desc(), ScheduleLog.id.desc())
                .first()
            )
            if running is not None:
                return schedule_log_out(running)
            row = (
                db.query(ScheduleLog)
                .filter(ScheduleLog.trigger == trigger)
                .order_by(ScheduleLog.started_at.desc(), ScheduleLog.id.desc())
                .first()
            )
            if row is not None and row.id != previous_id:
                return schedule_log_out(row)
        finally:
            db.close()
        time.sleep(0.05)
    raise RuntimeError("定时扫描未能启动")


def _loop() -> None:
    global _startup_checked
    while not _stop.is_set():
        wait = DISABLED_WAIT
        db: Session | None = SessionLocal()
        try:
            cfg = load_schedule(db)
            if not _startup_checked:
                _startup_checked = True
                if missed_scheduled_run(db):
                    db.close()
                    db = None
                    _safe_run_once("startup")
                    continue
            wait = seconds_until_tick(cfg.enabled, cfg.time)
        except Exception:
            wait = DISABLED_WAIT
        finally:
            if db is not None:
                db.close()
        triggered = _wake.wait(timeout=wait)
        if _stop.is_set():
            break
        if triggered:
            _wake.clear()
            continue
        db = SessionLocal()
        try:
            if not missed_scheduled_run(db):
                continue
        except Exception:
            continue
        finally:
            db.close()
        _safe_run_once("cron")
