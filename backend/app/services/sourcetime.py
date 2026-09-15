from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

SHANGHAI = ZoneInfo("Asia/Shanghai")
SOURCE_TIME_KEYS = (
    "pubdate",
    "datePublished",
    "dateCreated",
    "ctime",
    "zb_start_at",
    "alive_start_at",
    "lesson_start_at",
    "start_at",
    "zb_start_time",
    "liveStartTime",
    "live_start_time",
    "startTs",
    "start_ts",
    "startTime",
    "createTime",
    "create_time",
    "publish_time",
    "published_time",
    "oriCreateTime",
    "created_at",
    "unix_time",
    "liveTime",
)
MIN_TS = datetime(2000, 1, 1, tzinfo=timezone.utc)
MAX_TS = datetime(2100, 1, 1, tzinfo=timezone.utc)
_JSONLD_RE = re.compile(
    r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.I | re.S,
)
_PDF_DATE_RE = re.compile(
    r"^D:(\d{4})(\d{2})(\d{2})(\d{2})?(\d{2})?(\d{2})?(Z|[+-])?(\d{2})?'?(\d{2})?'?",
    re.I,
)
_HTML_TIME_PATTERNS = (
    r"var\s+createTime\s*=\s*['\"]([^'\"]+)['\"]",
    r"var\s+oriCreateTime\s*=\s*['\"]?(\d{10,13})",
    r"property=['\"]article:published_time['\"][^>]*content=['\"]([^'\"]+)['\"]",
    r"content=['\"]([^'\"]+)['\"][^>]*property=['\"]article:published_time['\"]",
    r"property=['\"]og:published_time['\"][^>]*content=['\"]([^'\"]+)['\"]",
    r"content=['\"]([^'\"]+)['\"][^>]*property=['\"]og:published_time['\"]",
    r"""\bdatePublished['"]?\s*[:=]\s*['"]([^'"]+)['"]""",
    r"""\bcreate_time\s*[:=]\s*['"]([^'"]+)['"]""",
    r"""\bpublish_time\s*[:=]\s*['"]([^'"]+)['"]""",
)


def ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _valid(value: datetime) -> datetime | None:
    utc = ensure_utc(value)
    if utc < MIN_TS or utc >= MAX_TS:
        return None
    return utc


def parse_source_datetime(value: Any) -> datetime | None:
    if value is None or value is False:
        return None
    if isinstance(value, datetime):
        return _valid(value)
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        if number > 1e12:
            number /= 1000
        try:
            return _valid(datetime.fromtimestamp(number, tz=timezone.utc))
        except (OSError, OverflowError, ValueError):
            return None
    text = str(value).strip()
    if not text:
        return None
    if re.fullmatch(r"-?\d+(\.\d+)?", text):
        return parse_source_datetime(float(text))
    normalized = text.replace("T", " ").replace("/", "-")
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    for fmt in (
        "%Y-%m-%d %H:%M:%S.%f%z",
        "%Y-%m-%d %H:%M:%S%z",
        "%Y-%m-%d %H:%M%z",
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
    ):
        try:
            parsed = datetime.strptime(normalized, fmt)
        except ValueError:
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=SHANGHAI)
        return _valid(parsed)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        parsed = None
    if parsed is not None:
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=SHANGHAI)
        return _valid(parsed)
    pdf = _parse_pdf_date(text)
    if pdf is not None:
        return pdf
    try:
        parsed = parsedate_to_datetime(text)
    except (TypeError, ValueError, OverflowError, IndexError):
        return None
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return _valid(parsed)


def pick_source_datetime(*sources: Any) -> datetime | None:
    for source in sources:
        if source is None:
            continue
        parsed = parse_source_datetime(source)
        if parsed is not None:
            return parsed
        if not isinstance(source, dict):
            continue
        for key in SOURCE_TIME_KEYS:
            if key not in source:
                continue
            parsed = parse_source_datetime(source.get(key))
            if parsed is not None:
                return parsed
    return None


def file_created_at(path: str | Path) -> datetime | None:
    try:
        stat = Path(path).stat()
    except OSError:
        return None
    stamp = getattr(stat, "st_birthtime", None) or stat.st_mtime
    return parse_source_datetime(stamp)


def pick_html_datetime(html: str) -> datetime | None:
    text = html or ""
    if not text.strip():
        return None
    for block in _JSONLD_RE.findall(text):
        try:
            payload = json.loads(block)
        except json.JSONDecodeError:
            continue
        picked = pick_source_datetime(*_walk_jsonld(payload))
        if picked is not None:
            return picked
    for pattern in _HTML_TIME_PATTERNS:
        match = re.search(pattern, text, re.I)
        if not match:
            continue
        parsed = parse_source_datetime(match.group(1))
        if parsed is not None:
            return parsed
    return None


def backfill_job_source_times(db) -> list[tuple[str, datetime]]:
    """用已保存的文档源文件，给缺少原片时间的文档任务补上发布时间。"""
    from app.models import Job
    from app.services.document import document_file_created_at
    from app.services.ingest.base import is_document_source

    filled: list[tuple[str, datetime]] = []
    for job in db.query(Job).order_by(Job.created_at.asc(), Job.id.asc()).all():
        if getattr(job, "source_created_at", None) is not None:
            continue
        if not is_document_source(job.source_type or ""):
            continue
        path = Path((job.source_path or "").strip())
        stamp = document_file_created_at(path) if path.is_file() else None
        if stamp is None:
            continue
        job.source_created_at = stamp
        filled.append((job.id, stamp))
    if filled:
        db.commit()
    return filled


def _parse_pdf_date(text: str) -> datetime | None:
    raw = (text or "").strip().replace(" ", "")
    match = _PDF_DATE_RE.match(raw)
    if not match:
        return None
    year, month, day, hour, minute, second, tzsign, tzh, tzm = match.groups()
    try:
        parsed = datetime(
            int(year),
            int(month),
            int(day),
            int(hour or 0),
            int(minute or 0),
            int(second or 0),
        )
    except ValueError:
        return None
    if tzsign in (None, ""):
        parsed = parsed.replace(tzinfo=SHANGHAI)
    elif tzsign.upper() == "Z":
        parsed = parsed.replace(tzinfo=timezone.utc)
    else:
        hours = int(tzh or 0)
        minutes = int(tzm or 0)
        offset = timedelta(hours=hours, minutes=minutes)
        if tzsign == "-":
            offset = -offset
        parsed = parsed.replace(tzinfo=timezone(offset))
    return _valid(parsed)


def _walk_jsonld(node):
    if isinstance(node, list):
        for item in node:
            yield from _walk_jsonld(item)
        return
    if isinstance(node, dict):
        yield node
        graph = node.get("@graph")
        if graph is not None:
            yield from _walk_jsonld(graph)
        for key, value in node.items():
            if key == "@graph":
                continue
            if isinstance(value, (dict, list)):
                yield from _walk_jsonld(value)
