from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import (
    AppSetting,
    Job,
    ScheduleLog,
    ScheduleRule,
    ScheduleRuleSite,
    ScheduleSite,
    Site,
    stamp_job_start,
    utcnow,
)
from app.schemas import ScheduleLogOut, ScheduleRuleIn, ScheduleRuleOut, ScheduleRuleSiteOut
from app.serializers import schedule_log_out
from app.services import jobqueue
from app.services.authctx import build_auth
from app.services.cron import CronError, CronSpec, describe_cron, parse_cron
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
SCHEDULE_DONE_STATUSES = ("ok", "partial", "failed")
SKIP_STATUS = "skipped"
BILI_CATALOG_PAUSE = 2.0
DISABLED_WAIT = 3600.0
BILI_RATE_LIMIT_KEEP = "后续稿件列表被限流，已保留已拉到的条目。请等几分钟再试，或到站点页填写 Cookie 保持登录态"

_stop = threading.Event()
_wake = threading.Event()
_run_lock = threading.Lock()
_thread: threading.Thread | None = None
_startup_checked = False
_skip_logged: set[tuple[str, str]] = set()


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


def shanghai_local(now: datetime | None = None) -> datetime:
    """定时任务一律按北京时间判断，进程时区是 UTC（容器默认）时也不会把 18:01 当成 UTC 18:01。"""
    stamp = now if now is not None else datetime.now(SHANGHAI)
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=SHANGHAI)
    return stamp.astimezone(SHANGHAI)


def shanghai_today_start(now: datetime | None = None) -> datetime:
    """定时扫描的下限：上海当天 0 点，只拉当天发布的内容。"""
    local = (now or datetime.now(tz=SHANGHAI)).astimezone(SHANGHAI)
    return local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)


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


def _time_text(value: str) -> str:
    try:
        hour, minute = parse_hhmm(value)
    except ValueError:
        return DEFAULT_TIME
    return format_hhmm(hour, minute)


def rule_cron_text(rule: ScheduleRule) -> str:
    """cron 优先；留空的旧配置按「每天 HH:MM」跑，不需要数据迁移。"""
    text = (getattr(rule, "cron", "") or "").strip()
    if text:
        return text
    hour, minute = parse_hhmm(_time_text(rule.time))
    return f"{minute} {hour} * * *"


def rule_spec(rule: ScheduleRule) -> CronSpec:
    return parse_cron(rule_cron_text(rule))


def rule_trigger_point(rule: ScheduleRule, now: datetime | None = None) -> datetime | None:
    """now（含）之前最近的一个触发点，也就是「这一轮本该跑的时刻」。"""
    return rule_spec(rule).latest_at_or_before(shanghai_local(now))


def seconds_until_rule_tick(rule: ScheduleRule, now: datetime | None = None) -> float:
    """距离这条配置下一次触发还有多少秒；cron 与「每天 HH:MM」统一在这里算。"""
    local = shanghai_local(now)
    target = rule_spec(rule).next_after(local)
    return max(1.0, (target - local).total_seconds())


def run_scan_since(rule: ScheduleRule, trigger: str, now: datetime | None = None) -> datetime:
    """扫描内容的下限：定时触发从上一次触发点算起，每周 / 每月这类低频规则才不会漏内容；
    手动触发依旧只看当天，跟以前一样。"""
    if trigger != "manual":
        try:
            spec = rule_spec(rule)
            point = spec.latest_at_or_before(shanghai_local(now))
            if point is not None:
                previous = spec.latest_at_or_before(point - timedelta(minutes=1))
                return (previous or point).astimezone(timezone.utc)
        except CronError:
            pass
    return shanghai_today_start(now)


def _enabled_rules(db: Session) -> list[ScheduleRule]:
    return (
        db.query(ScheduleRule)
        .filter(ScheduleRule.enabled.is_(True))
        .order_by(ScheduleRule.created_at.asc(), ScheduleRule.id.asc())
        .all()
    )


def enabled_rule_ids(db: Session) -> list[str]:
    return [rule.id for rule in _enabled_rules(db)]


def _rule_sites(db: Session, rule_id: str) -> dict[str, ScheduleRuleSite]:
    rows = db.query(ScheduleRuleSite).filter(ScheduleRuleSite.rule_id == rule_id).all()
    return {row.site_id: row for row in rows}


def get_rule(db: Session, rule_id: str) -> ScheduleRule | None:
    text = (rule_id or "").strip()
    if not text:
        return None
    return db.get(ScheduleRule, text)


def _default_rule(db: Session) -> ScheduleRule | None:
    enabled = _enabled_rules(db)
    if enabled:
        return enabled[0]
    return db.query(ScheduleRule).order_by(ScheduleRule.created_at.asc(), ScheduleRule.id.asc()).first()


def rule_out(db: Session, rule: ScheduleRule) -> ScheduleRuleOut:
    configs = _rule_sites(db, rule.id)
    sites: list[ScheduleRuleSiteOut] = []
    for site in _schedulable_sites(db):
        row = configs.get(site.id)
        sites.append(
            ScheduleRuleSiteOut(
                site_id=site.id,
                name=site.name,
                adapter=site.adapter,
                enabled=bool(row.enabled) if row else False,
                catalog_id=(row.catalog_id if row else "") or "",
                catalog_hint=CATALOG_HINTS.get(site.adapter, ""),
            )
        )
    cron_text = (getattr(rule, "cron", "") or "").strip()
    cron_hint = ""
    next_run_at = None
    if cron_text:
        try:
            spec = parse_cron(cron_text)
        except CronError:
            spec = None
        if spec is not None:
            cron_hint = describe_cron(spec)
            if rule.enabled:
                next_run_at = naive_utc(spec.next_after(shanghai_local()))
    return ScheduleRuleOut(
        id=rule.id,
        name=rule.name or "",
        enabled=bool(rule.enabled),
        time=_time_text(rule.time),
        cron=cron_text,
        cron_hint=cron_hint,
        next_run_at=next_run_at,
        max_jobs=parse_max_jobs(rule.max_jobs),
        domain_id=rule.domain_id or "",
        digest_enabled=bool(rule.digest_enabled),
        sites=sites,
    )


def list_rules(db: Session) -> list[ScheduleRuleOut]:
    rows = db.query(ScheduleRule).order_by(ScheduleRule.created_at.asc(), ScheduleRule.id.asc()).all()
    return [rule_out(db, row) for row in rows]


def list_schedule_sites(db: Session) -> list[ScheduleRuleSiteOut]:
    """可参与定时的站点清单，供界面新建配置时勾选。"""
    return [
        ScheduleRuleSiteOut(
            site_id=site.id,
            name=site.name,
            adapter=site.adapter,
            enabled=False,
            catalog_id="",
            catalog_hint=CATALOG_HINTS.get(site.adapter, ""),
        )
        for site in _schedulable_sites(db)
    ]


def save_rule(db: Session, payload: ScheduleRuleIn, rule_id: str | None = None) -> ScheduleRuleOut:
    cron_text = (payload.cron or "").strip()
    if cron_text:
        # 填了 cron 就以 cron 为准；time 只留给界面当「每天几点」的兜底
        cron_text = parse_cron(cron_text).text
        time_text = _time_text(payload.time)
    else:
        hour, minute = parse_hhmm(payload.time)
        time_text = format_hhmm(hour, minute)
    known = {site.id: site for site in _schedulable_sites(db)}
    row = get_rule(db, rule_id) if rule_id else None
    if rule_id and row is None:
        raise LookupError("定时配置不存在")
    # 先校验站点与内容源，再落库，避免校验失败留下半成品配置
    normalized: list[tuple[str, bool, str]] = []
    seen: set[str] = set()
    for item in payload.sites:
        if item.site_id in seen:
            continue
        seen.add(item.site_id)
        site = known.get(item.site_id)
        if site is None:
            raise ValueError("只能为小鹅通、约牛或 B 站配置定时任务")
        catalog_id = (item.catalog_id or "").strip()
        if item.enabled and site.adapter in {"xiaoe", "bilibili"} and not split_catalog_ids(catalog_id):
            label = "小鹅通店铺 app_id" if site.adapter == "xiaoe" else "B 站 UP 的 mid"
            raise ValueError(f"{site.name} 已启用定时，请填写{label}，多个可用逗号分隔")
        normalized.append((item.site_id, bool(item.enabled), catalog_id))
    if row is None:
        row = ScheduleRule(name=(payload.name or "").strip() or "定时配置")
        db.add(row)
        db.flush()
    row.name = (payload.name or "").strip() or row.name or "定时配置"
    row.enabled = bool(payload.enabled)
    row.time = time_text
    row.cron = cron_text
    row.max_jobs = parse_max_jobs(payload.max_jobs)
    row.domain_id = (payload.domain_id or "").strip()
    row.digest_enabled = bool(payload.digest_enabled)
    current = _rule_sites(db, row.id)
    for site_id, enabled, catalog_id in normalized:
        config = current.get(site_id)
        if config is None:
            config = ScheduleRuleSite(rule_id=row.id, site_id=site_id)
            db.add(config)
        config.enabled = enabled
        config.catalog_id = catalog_id
    db.commit()
    db.refresh(row)
    wake_scheduler()
    return rule_out(db, row)


def delete_rule(db: Session, rule_id: str) -> dict:
    row = get_rule(db, rule_id)
    if row is None:
        raise LookupError("定时配置不存在")
    db.query(ScheduleRuleSite).filter(ScheduleRuleSite.rule_id == row.id).delete()
    db.delete(row)
    db.commit()
    wake_scheduler()
    return {"ok": True}


def migrate_schedule_rules(db: Session) -> None:
    """旧版只有一套定时配置：升级时搬成一条「默认」配置，并清掉旧的全局设置。"""
    if db.query(ScheduleRule).count() > 0:
        return
    keys = (
        "schedule_enabled",
        "schedule_time",
        "schedule_max_jobs",
        "schedule_domain_id",
        "schedule_digest_enabled",
    )
    stored = {row.key: row.value for row in db.query(AppSetting).filter(AppSetting.key.in_(keys)).all()}
    legacy_sites = db.query(ScheduleSite).all()
    if not stored and not legacy_sites:
        return
    rule = ScheduleRule(
        name="默认",
        enabled=parse_flag(stored.get("schedule_enabled", "0"), False),
        time=_time_text(stored.get("schedule_time", DEFAULT_TIME)),
        max_jobs=parse_max_jobs(stored.get("schedule_max_jobs", str(DEFAULT_MAX_JOBS))),
        domain_id=stored.get("schedule_domain_id", "") or job_domain_id(""),
        digest_enabled=parse_flag(stored.get("schedule_digest_enabled", "1"), True),
    )
    db.add(rule)
    db.flush()
    for item in legacy_sites:
        db.add(
            ScheduleRuleSite(
                rule_id=rule.id,
                site_id=item.site_id,
                enabled=bool(item.enabled),
                catalog_id=item.catalog_id or "",
            )
        )
    for key in (*keys, "schedule_since"):
        stale = db.get(AppSetting, key)
        if stale is not None:
            db.delete(stale)
    db.commit()


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


def run_once(
    trigger: str = "cron",
    execute: bool = True,
    db: Session | None = None,
    rule_id: str | None = None,
) -> ScheduleLogOut:
    own_session = db is None
    if db is None:
        db = SessionLocal()
    created_ids: list[str] = []
    digest_log_id: str | None = None
    try:
        with _run_lock:
            rule = get_rule(db, rule_id) if rule_id else _default_rule(db)
            if rule is None:
                raise ValueError("还没有定时配置")
            if trigger != "manual":
                if not rule.enabled:
                    raise ValueError("定时任务未启用")
                if not missed_scheduled_run(db, rule):
                    local = shanghai_local()
                    try:
                        point = rule_trigger_point(rule, local)
                    except CronError:
                        raise ValueError("定时时间配置有误，请重新保存这条配置") from None
                    if point is None or point.date() != local.date():
                        raise ValueError("未到今天的定时时间")
                    raise ValueError("本轮定时任务已经执行过")
            since = run_scan_since(rule, trigger)
            today = _shanghai_day(datetime.now(tz=SHANGHAI))
            remaining = parse_max_jobs(rule.max_jobs)
            domain_id = job_domain_id(rule.domain_id)
            existing = _existing_catalog(db)
            log = ScheduleLog(
                trigger=trigger,
                status="running",
                summary="正在扫描站点",
                rule_id=rule.id,
                rule_name=rule.name or "",
            )
            db.add(log)
            db.commit()
            db.refresh(log)

            details: list[dict] = []
            created_total = 0
            skipped_total = 0
            configs = _rule_sites(db, rule.id)
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
            if rule.digest_enabled:
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
    # 整批算队列里的一项：同一时刻只有一个任务真正转写，和手动创建的任务共用一条队伍，
    # 免得两个线程各跑一个任务把 CPU 摊薄。整批跑完再出汇总。
    jobqueue.enqueue("", lambda: _run_created_jobs(job_ids, digest_log_id=digest_log_id))


def seconds_until_tick(enabled: bool, time_text: str, now: datetime | None = None) -> float:
    """「每天 HH:MM」的下一次触发还有多少秒（保留给每天固定时间的配置与测试用）。"""
    if not enabled:
        return DISABLED_WAIT
    hour, minute = parse_hhmm(time_text or DEFAULT_TIME)
    local = shanghai_local(now)
    target = parse_cron(f"{minute} {hour} * * *").next_after(local)
    return max(1.0, (target - local).total_seconds())


def seconds_until_next_tick(rules: list[ScheduleRule], now: datetime | None = None) -> float:
    waits = [seconds_until_rule_tick(rule, now) for rule in rules if rule.enabled]
    return min(waits) if waits else DISABLED_WAIT


def missed_scheduled_run(db: Session, rule: ScheduleRule, now: datetime | None = None) -> bool:
    """这一轮触发点是否还没跑过；今天还没到触发点的一律不算「漏跑」。"""
    if not rule.enabled:
        return False
    local = shanghai_local(now)
    try:
        point = rule_trigger_point(rule, local)
    except CronError:
        return False
    if point is None or point.date() != local.date():
        return False
    start_utc = naive_utc(point)
    row = (
        db.query(ScheduleLog)
        .filter(ScheduleLog.rule_id == rule.id)
        .filter(ScheduleLog.finished_at.isnot(None))
        .filter(ScheduleLog.status.in_(SCHEDULE_DONE_STATUSES))
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


def note_schedule_skip(
    trigger: str,
    summary: str,
    rule_id: str = "",
    rule_name: str = "",
    now: datetime | None = None,
    force: bool = False,
) -> None:
    """到点但没执行时也写一条记录，避免只看到一片空白；同一天同一条配置只留一条。"""
    global _skip_logged
    local = shanghai_local(now)
    stamp = naive_utc(local)
    key = (rule_id, local.strftime("%Y-%m-%d"))
    if not force and key in _skip_logged:
        return
    _skip_logged.add(key)
    db = SessionLocal()
    try:
        db.add(
            ScheduleLog(
                trigger=trigger,
                status=SKIP_STATUS,
                summary=summary,
                started_at=stamp,
                finished_at=stamp,
                rule_id=rule_id,
                rule_name=rule_name,
            )
        )
        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()


def _safe_run_once(trigger: str, rule_id: str = "") -> None:
    try:
        run_once(trigger, rule_id=rule_id or None)
    except Exception as exc:
        note_schedule_skip(trigger, f"本轮没有执行：{exc}", rule_id=rule_id, force=trigger == "manual")


def _rule_ids_for_run(db: Session, rule_id: str | None = None) -> list[str]:
    if rule_id:
        return [rule_id]
    return enabled_rule_ids(db)


def _run_due_ticks(trigger: str = "cron", now: datetime | None = None) -> list[str]:
    """到点评估（逐条配置）：该跑就跑，已跑过或检查失败也留痕。"""
    global _skip_logged
    stamp = shanghai_local(now)
    pending: list[str] = []
    notes: list[tuple[str, str, str, bool]] = []
    db = SessionLocal()
    try:
        for rule in _enabled_rules(db):
            try:
                point = rule_trigger_point(rule, stamp)
            except CronError:
                notes.append(
                    (rule.id, rule.name or "", "定时时间配置有误，本轮未扫描，请重新保存这条配置", True)
                )
                continue
            if point is None or point.date() != stamp.date():
                continue
            try:
                due = missed_scheduled_run(db, rule, stamp)
            except Exception as exc:
                notes.append((rule.id, rule.name or "", f"检查定时状态失败，本轮未扫描：{exc}", True))
                continue
            if due:
                pending.append(rule.id)
            else:
                notes.append((rule.id, rule.name or "", "这个触发点已经执行过定时任务，本轮到点不再扫描", False))
    except Exception:
        return []
    finally:
        db.close()
    for rule_id, rule_name, summary, force in notes:
        note_schedule_skip(trigger, summary, rule_id=rule_id, rule_name=rule_name, now=stamp, force=force)
    for rule_id in pending:
        _skip_logged = {item for item in _skip_logged if item[0] != rule_id}
        _safe_run_once(trigger, rule_id)
    return pending


def _run_rules_safe(trigger: str, rule_id: str | None = None) -> None:
    db = SessionLocal()
    try:
        targets = _rule_ids_for_run(db, rule_id)
    finally:
        db.close()
    for target in targets:
        _safe_run_once(trigger, target)


def start_detached_run(trigger: str = "manual", rule_id: str | None = None) -> ScheduleLogOut:
    db = SessionLocal()
    try:
        if not _rule_ids_for_run(db, rule_id):
            raise RuntimeError("还没有启用的定时配置")
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

    thread = threading.Thread(target=_run_rules_safe, args=(trigger, rule_id), name="schedule-run", daemon=True)
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
            rules = _enabled_rules(db)
            if not _startup_checked:
                _startup_checked = True
                pending = [rule.id for rule in rules if missed_scheduled_run(db, rule)]
                if pending:
                    db.close()
                    db = None
                    for rule_id in pending:
                        _safe_run_once("startup", rule_id)
                    continue
            wait = seconds_until_next_tick(rules)
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
        _run_due_ticks("cron")
