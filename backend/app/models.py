from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
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


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    title: Mapped[str] = mapped_column(String(255), default="")
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
    source_created_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


def stamp_job_start(job: Job) -> None:
    job.started_at = utcnow()
