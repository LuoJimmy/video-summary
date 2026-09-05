import os

from sqlalchemy.orm import Session

from app.config import settings
from app.models import AppSetting
from app.schemas import AppSettingsOut
from app.services.domain import list_presets, load_active_pack, save_active_pack


KEYS = (
    "transcribe_base_url",
    "transcribe_api_key",
    "transcribe_model",
    "summarize_base_url",
    "summarize_api_key",
    "summarize_model",
    "capture_seconds",
    "summarize_concurrency",
    "transcribe_threads",
    "transcribe_fast",
    "ai_proofread",
    "show_transcript",
)
FLAG_KEYS = {"ai_proofread", "show_transcript", "transcribe_fast"}


def _get(db: Session, key: str, default: str = "") -> str:
    row = db.get(AppSetting, key)
    return row.value if row else default


def parse_concurrency(value: object, default: int = 3) -> int:
    try:
        number = int(str(value).strip() or default)
    except (TypeError, ValueError):
        number = default
    return max(1, min(number, 8))


def cpu_count() -> int:
    return max(1, os.cpu_count() or 1)


def default_transcribe_threads(cpus: int | None = None) -> int:
    """本机逻辑核的 80%，至少 1 路。"""
    n = cpu_count() if cpus is None else max(1, int(cpus))
    return max(1, min(n, int(n * 0.8) or 1))


def parse_transcribe_threads(value: object, cpus: int | None = None) -> int:
    n = cpu_count() if cpus is None else max(1, int(cpus))
    default = default_transcribe_threads(n)
    try:
        number = int(str(value).strip() or default)
    except (TypeError, ValueError):
        number = default
    if number <= 0:
        number = default
    return max(1, min(number, n))


def parse_flag(value: object, default: bool = True) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default


def _flag(db: Session, key: str, default: bool = True) -> bool:
    fallback = "1" if default else "0"
    return parse_flag(_get(db, key, fallback), default)


def _flag_text(value: object, default: bool = True) -> str:
    return "1" if parse_flag(value, default) else "0"


def migrate_settings_defaults(db: Session) -> None:
    changed = False
    transcribe = db.get(AppSetting, "transcribe_model")
    if transcribe is not None:
        current = transcribe.value.strip().lower().replace("_", "-")
        # 空、云端 whisper-1、以及曾被误迁走的 small，都回到 SenseVoice 默认
        if current in {"", "whisper-1", "small"}:
            transcribe.value = settings.default_transcribe_model
            changed = True
    summarize = db.get(AppSetting, "summarize_model")
    if summarize is not None and summarize.value.strip() in {"", "deepseek-chat"}:
        summarize.value = settings.default_summarize_model
        changed = True
    if changed:
        db.commit()


def load_settings(db: Session) -> AppSettingsOut:
    return AppSettingsOut(
        transcribe_base_url=_get(db, "transcribe_base_url", settings.default_transcribe_base_url),
        transcribe_api_key=_get(db, "transcribe_api_key"),
        transcribe_model=_get(db, "transcribe_model", settings.default_transcribe_model),
        summarize_base_url=_get(db, "summarize_base_url", settings.default_summarize_base_url),
        summarize_api_key=_get(db, "summarize_api_key"),
        summarize_model=_get(db, "summarize_model", settings.default_summarize_model),
        capture_seconds=_get(db, "capture_seconds", "180"),
        summarize_concurrency=parse_concurrency(
            _get(db, "summarize_concurrency", str(settings.summarize_concurrency)),
            settings.summarize_concurrency,
        ),
        transcribe_threads=parse_transcribe_threads(_get(db, "transcribe_threads")),
        transcribe_fast=_flag(db, "transcribe_fast", False),
        ai_proofread=_flag(db, "ai_proofread", True),
        show_transcript=_flag(db, "show_transcript", True),
        cpu_count=cpu_count(),
        domain_pack=load_active_pack(),
        domain_presets=list_presets(),
    )


def save_settings(db: Session, payload: dict) -> AppSettingsOut:
    if "domain_pack" in payload and payload["domain_pack"] is not None:
        save_active_pack(payload["domain_pack"])
    for key in KEYS:
        if key not in payload:
            continue
        if key == "summarize_concurrency":
            value = str(parse_concurrency(payload[key], settings.summarize_concurrency))
        elif key == "transcribe_threads":
            value = str(parse_transcribe_threads(payload[key]))
        elif key in FLAG_KEYS:
            default = False if key == "transcribe_fast" else True
            value = _flag_text(payload[key], default)
        else:
            value = payload[key] or ""
        row = db.get(AppSetting, key)
        if row is None:
            db.add(AppSetting(key=key, value=value))
        else:
            row.value = value
    db.commit()
    return load_settings(db)
