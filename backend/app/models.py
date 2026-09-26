import os
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return uuid4().hex


class AuthProfile(Base):
    __tablename__ = "auth_profiles"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(120))
    cookie: Mapped[str] = mapped_column(Text, default="")
    extra_headers: Mapped[str] = mapped_column(Text, default="{}")
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    sites: Mapped[list["Site"]] = relationship(back_populates="auth_profile")


class Site(Base):
    __tablename__ = "sites"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(120))
    adapter: Mapped[str] = mapped_column(String(32), default="generic")
    domain_patterns: Mapped[str] = mapped_column(Text, default="[]")
    auth_profile_id: Mapped[str | None] = mapped_column(ForeignKey("auth_profiles.id"), nullable=True)
    cookie_override: Mapped[str] = mapped_column(Text, default="")
    extra_headers: Mapped[str] = mapped_column(Text, default="{}")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    auth_profile: Mapped[AuthProfile | None] = relationship(back_populates="sites")


class ScheduleSite(Base):
    __tablename__ = "schedule_sites"

    site_id: Mapped[str] = mapped_column(ForeignKey("sites.id"), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    catalog_id: Mapped[str] = mapped_column(Text, default="")


class ScheduleRule(Base):
    __tablename__ = "schedule_rules"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(120), default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    time: Mapped[str] = mapped_column(String(5), default="08:00")
    # 5 段式 cron（分 时 日 月 周）；留空表示按上面的 time 每天跑一次
    cron: Mapped[str] = mapped_column(String(120), default="")
    max_jobs: Mapped[int] = mapped_column(Integer, default=5)
    domain_id: Mapped[str] = mapped_column(String(32), default="")
    digest_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class ScheduleRuleSite(Base):
    __tablename__ = "schedule_rule_sites"

    rule_id: Mapped[str] = mapped_column(ForeignKey("schedule_rules.id"), primary_key=True)
    site_id: Mapped[str] = mapped_column(ForeignKey("sites.id"), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    catalog_id: Mapped[str] = mapped_column(Text, default="")


class ScheduleLog(Base):
    __tablename__ = "schedule_logs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=None)
    trigger: Mapped[str] = mapped_column(String(16), default="cron")
    status: Mapped[str] = mapped_column(String(32), default="running")
    summary: Mapped[str] = mapped_column(Text, default="")
    detail_json: Mapped[str] = mapped_column(Text, default="[]")
    digest_job_id: Mapped[str] = mapped_column(String(32), default="")
    rule_id: Mapped[str] = mapped_column(String(32), default="")
    rule_name: Mapped[str] = mapped_column(String(120), default="")


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")


class Job(Base):
    __tablename__ = "jobs"
    # 与 app/database.py 的 JOB_INDEXES 保持一致：新库建表即带索引，旧库靠启动迁移补建
    __table_args__ = (
        Index("idx_jobs_status", "status"),
        Index("idx_jobs_stamp", text("coalesce(source_created_at, created_at)"), "created_at", "id"),
        Index("idx_jobs_created_at", "created_at", "id"),
        Index("idx_jobs_updated_at", "updated_at"),
        Index("idx_jobs_domain_updated_at", "domain_id", "updated_at"),
        Index("idx_jobs_schedule_log_id", "schedule_log_id"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    title: Mapped[str] = mapped_column(String(255), default="")
    author: Mapped[str] = mapped_column(String(120), default="")
    source_url: Mapped[str] = mapped_column(Text, default="")
    source_type: Mapped[str] = mapped_column(String(32), default="unknown")
    site_id: Mapped[str | None] = mapped_column(ForeignKey("sites.id"), nullable=True)
    auth_profile_id: Mapped[str | None] = mapped_column(ForeignKey("auth_profiles.id"), nullable=True)
    domain_id: Mapped[str] = mapped_column(String(32), default="")
    media_url: Mapped[str] = mapped_column(Text, default="")
    media_url_override: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default="pending")
    stage: Mapped[str] = mapped_column(String(32), default="queued")
    progress: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str] = mapped_column(Text, default="")
    transcript_json: Mapped[str] = mapped_column(Text, default="")
    summary_json: Mapped[str] = mapped_column(Text, default="")
    audio_path: Mapped[str] = mapped_column(Text, default="")
    source_path: Mapped[str] = mapped_column(Text, default="")
    timing_json: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=None)
    # 开始跑这个任务的进程号（`stamp_job_start()` 里写）：进程被强杀后靠它判断「转写中」是不是没人跑了
    owner_pid: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    source_created_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=None)
    summarize_document: Mapped[bool] = mapped_column(Boolean, default=False)
    schedule_log_id: Mapped[str] = mapped_column(String(32), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class KnowledgeConversation(Base):
    __tablename__ = "knowledge_conversations"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    domain_id: Mapped[str] = mapped_column(String(32), default="")
    title: Mapped[str] = mapped_column(String(255), default="")
    messages_json: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


def stamp_job_start(job: Job) -> None:
    """记下开始时间和跑它的进程（进程被强杀后，启动时靠 owner_pid 认出没人跑的「转写中」）。"""
    job.started_at = utcnow()
    job.owner_pid = os.getpid()
