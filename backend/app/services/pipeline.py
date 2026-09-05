import time
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.models import Job, utcnow
from app.schemas import TranscriptSegment
from app.services.authctx import build_auth
from app.services.cancel import JobCancelled, job_scope, raise_if_cancelled
from app.services.domain import job_pack_scope
from app.services.ingest import resolve_media
from app.services.jsonutil import dumps, loads
from app.services.media import MediaError, MediaExtractor, default_extractor
from app.services.proofread import proofread_transcript
from app.services.settings_store import load_settings
from app.services.sourcetime import pick_source_datetime
from app.services.summarize import SummarizeError, Summarizer, default_summarizer
from app.services.textnorm import normalize_transcript
from app.services.transcribe import TranscribeError, Transcriber, default_transcriber


class StageTimer:
    def __init__(self) -> None:
        self._started: dict[str, float] = {}
        self.seconds: dict[str, float] = {}

    def start(self, name: str) -> None:
        self._started[name] = time.perf_counter()

    def stop(self, name: str) -> None:
        began = self._started.pop(name, None)
        if began is None:
            return
        self.seconds[name] = round(self.seconds.get(name, 0) + (time.perf_counter() - began), 1)

    def payload(self) -> dict[str, float]:
        data = dict(self.seconds)
        if data:
            data["total"] = round(sum(self.seconds.values()), 1)
        return data


class Pipeline:
    def __init__(
        self,
        extractor: MediaExtractor | None = None,
        transcriber: Transcriber | None = None,
        summarizer: Summarizer | None = None,
    ) -> None:
        self.extractor = extractor or default_extractor()
        self.transcriber = transcriber or default_transcriber()
        self.summarizer = summarizer or default_summarizer()

    def run_job(self, job_id: str) -> None:
        db = SessionLocal()
        try:
            with job_scope(job_id):
                self._run(db, job_id)
        except JobCancelled:
            job = db.get(Job, job_id)
            if job is not None and job.status not in {"cancelled", "done"}:
                self._update(db, job, status="cancelled", stage="cancelled", error="已取消")
        finally:
            db.close()

    def resummarize_job(self, job_id: str) -> None:
        db = SessionLocal()
        try:
            with job_scope(job_id):
                job = db.get(Job, job_id)
                if job is None:
                    return
                with job_pack_scope(job.domain_id):
                    raise_if_cancelled()
                    if job.status == "cancelled":
                        return
                    raw = loads(job.transcript_json, [])
                    if not raw:
                        raise SummarizeError("没有转写结果，无法只重跑总结")
                    segments = [
                        TranscriptSegment.model_validate(item).model_copy(update={"text": normalize_transcript(item.get("text") or "")})
                        for item in raw
                    ]
                    timer = StageTimer()
                    timer.start("summarizing")
                    self._update(
                        db,
                        job,
                        transcript_json=dumps([item.model_dump() for item in segments]),
                        status="running",
                        stage="summarizing",
                        progress=80,
                        error="",
                    )
                    raise_if_cancelled()
                    summary = self.summarizer.summarize(segments, load_settings(db))
                    timer.stop("summarizing")
                    raise_if_cancelled()
                    self._update(
                        db,
                        job,
                        summary_json=summary.model_dump_json(),
                        timing_json=dumps(timer.payload()),
                        status="done",
                        stage="done",
                        progress=100,
                    )
        except JobCancelled:
            job = db.get(Job, job_id)
            if job is not None and job.status not in {"cancelled", "done"}:
                self._update(db, job, status="cancelled", stage="cancelled", error="已取消")
        except (SummarizeError, RuntimeError) as exc:
            job = db.get(Job, job_id)
            if job is not None and job.status != "cancelled":
                self._update(db, job, status="failed", error=str(exc))
        except Exception as exc:
            job = db.get(Job, job_id)
            if job is not None and job.status != "cancelled":
                self._update(db, job, status="failed", error=f"未预期错误：{exc}")
        finally:
            db.close()

    def proofread_job(self, job_id: str) -> None:
        db = SessionLocal()
        try:
            with job_scope(job_id):
                job = db.get(Job, job_id)
                if job is None:
                    return
                with job_pack_scope(job.domain_id):
                    raise_if_cancelled()
                    if job.status == "cancelled":
                        return
                    raw = loads(job.transcript_json, [])
                    if not raw:
                        raise SummarizeError("没有转写结果，无法校对")
                    segments = [TranscriptSegment.model_validate(item) for item in raw]
                    timer = StageTimer()
                    timer.start("proofreading")
                    self._update(db, job, status="running", stage="proofreading", progress=70, error="")
                    raise_if_cancelled()
                    segments = proofread_transcript(segments, load_settings(db), use_llm=True)
                    timer.stop("proofreading")
                    timer.start("summarizing")
                    self._update(
                        db,
                        job,
                        transcript_json=dumps([item.model_dump() for item in segments]),
                        timing_json=dumps(timer.payload()),
                        stage="summarizing",
                        progress=80,
                    )
                    raise_if_cancelled()
                    summary = self.summarizer.summarize(segments, load_settings(db))
                    timer.stop("summarizing")
                    raise_if_cancelled()
                    self._update(
                        db,
                        job,
                        summary_json=summary.model_dump_json(),
                        timing_json=dumps(timer.payload()),
                        status="done",
                        stage="done",
                        progress=100,
                    )
        except JobCancelled:
            job = db.get(Job, job_id)
            if job is not None and job.status not in {"cancelled", "done"}:
                self._update(db, job, status="cancelled", stage="cancelled", error="已取消")
        except (SummarizeError, RuntimeError) as exc:
            job = db.get(Job, job_id)
            if job is not None and job.status != "cancelled":
                self._update(db, job, status="failed", error=str(exc))
        except Exception as exc:
            job = db.get(Job, job_id)
            if job is not None and job.status != "cancelled":
                self._update(db, job, status="failed", error=f"未预期错误：{exc}")
        finally:
            db.close()

    def retranscribe_job(self, job_id: str, continue_after: bool = True) -> None:
        db = SessionLocal()
        try:
            with job_scope(job_id):
                job = db.get(Job, job_id)
                if job is None:
                    return
                with job_pack_scope(job.domain_id):
                    raise_if_cancelled()
                    if job.status == "cancelled":
                        return
                    timer = StageTimer()
                    audio_path = settings.resolve_job_audio_path(job.id, job.audio_path)
                    app_settings = load_settings(db)
                    if not audio_path.exists() or audio_path.stat().st_size == 0:
                        timer.start("extracting")
                        self._update(db, job, status="running", stage="extracting", progress=25, error="")
                        source = job.source_path or job.source_url
                        auth = build_auth(db, url=job.source_url, site_id=job.site_id, auth_profile_id=job.auth_profile_id)
                        resolved = resolve_media(source, auth, media_url_override=job.media_url_override)
                        if resolved.needs_media_url or not resolved.media_url:
                            raise RuntimeError(resolved.message or "没有可抽音的媒体地址，无法只重跑转写")
                        try:
                            max_seconds = int(app_settings.capture_seconds or "0")
                        except ValueError:
                            max_seconds = 180
                        self.extractor.extract_audio(
                            resolved.media_url,
                            audio_path,
                            extra_headers=resolved.headers,
                            max_seconds=max_seconds or None,
                        )
                        timer.stop("extracting")
                        self._update(db, job, audio_path=str(audio_path), media_url=resolved.media_url)
                    timer.start("transcribing")
                    self._update(db, job, audio_path=str(audio_path), status="running", stage="transcribing", progress=50, error="")
                    raise_if_cancelled()
                    segments = self.transcriber.transcribe(audio_path, app_settings)
                    timer.stop("transcribing")
                    raise_if_cancelled()
                    if not continue_after:
                        self._update(
                            db,
                            job,
                            transcript_json=dumps([item.model_dump() for item in segments]),
                            timing_json=dumps(timer.payload()),
                            status="done",
                            stage="done",
                            progress=100,
                        )
                        return
                    segments = self._maybe_ai_proofread(db, job, segments, app_settings, timer)
                    self._update(
                        db,
                        job,
                        transcript_json=dumps([item.model_dump() for item in segments]),
                        timing_json=dumps(timer.payload()),
                        stage="summarizing",
                        progress=75,
                    )
                    timer.start("summarizing")
                    summary = self.summarizer.summarize(segments, app_settings)
                    timer.stop("summarizing")
                    raise_if_cancelled()
                    self._update(
                        db,
                        job,
                        summary_json=summary.model_dump_json(),
                        timing_json=dumps(timer.payload()),
                        status="done",
                        stage="done",
                        progress=100,
                    )
        except JobCancelled:
            job = db.get(Job, job_id)
            if job is not None and job.status not in {"cancelled", "done"}:
                self._update(db, job, status="cancelled", stage="cancelled", error="已取消")
        except (MediaError, TranscribeError, SummarizeError, RuntimeError) as exc:
            job = db.get(Job, job_id)
            if job is not None and job.status != "cancelled":
                self._update(db, job, status="failed", error=str(exc))
        except Exception as exc:
            job = db.get(Job, job_id)
            if job is not None and job.status != "cancelled":
                self._update(db, job, status="failed", error=f"未预期错误：{exc}")
        finally:
            db.close()

    def _maybe_ai_proofread(self, db: Session, job: Job, segments: list[TranscriptSegment], app_settings, timer: StageTimer) -> list[TranscriptSegment]:
        if not app_settings.ai_proofread:
            return segments
        timer.start("proofreading")
        self._update(
            db,
            job,
            transcript_json=dumps([item.model_dump() for item in segments]),
            timing_json=dumps(timer.payload()),
            stage="proofreading",
            progress=62,
        )
        raise_if_cancelled()
        segments = proofread_transcript(segments, app_settings, use_llm=True)
        timer.stop("proofreading")
        raise_if_cancelled()
        return segments

    def _update(self, db: Session, job: Job, **fields) -> None:
        next_status = fields.get("status")
        if next_status != "cancelled":
            raise_if_cancelled(job.id)
            if job.status == "cancelled":
                raise JobCancelled()
        for key, value in fields.items():
            setattr(job, key, value)
        if fields.get("status") == "running" and getattr(job, "started_at", None) is None:
            job.started_at = utcnow()
        db.add(job)
        db.commit()
        db.refresh(job)

    def _run(self, db: Session, job_id: str) -> None:
        job = db.get(Job, job_id)
        if job is None:
            return
        with job_pack_scope(job.domain_id):
            self._run_unlocked(db, job_id)

    def _run_unlocked(self, db: Session, job_id: str) -> None:
        job = db.get(Job, job_id)
        if job is None:
            return
        try:
            raise_if_cancelled()
            if job.status == "cancelled":
                return
            timer = StageTimer()
            timer.start("resolving")
            self._update(db, job, status="running", stage="resolving", progress=8, error="", timing_json="")
            source = job.source_path or job.source_url
            auth = build_auth(db, url=job.source_url, site_id=job.site_id, auth_profile_id=job.auth_profile_id)
            resolved = resolve_media(source, auth, media_url_override=job.media_url_override)
            source_created_at = job.source_created_at or resolved.created_at or pick_source_datetime(resolved.extra)
            title = job.title or resolved.title or "未命名任务"
            if resolved.needs_media_url or not resolved.media_url:
                raise RuntimeError(resolved.message or "无法解析媒体地址，请填写媒体地址覆盖")
            timer.stop("resolving")

            raise_if_cancelled()
            timer.start("extracting")
            self._update(
                db,
                job,
                title=title,
                source_type=resolved.source_type,
                source_created_at=source_created_at,
                media_url=resolved.media_url,
                site_id=auth.site.id if auth.site else job.site_id,
                auth_profile_id=auth.profile.id if auth.profile else job.auth_profile_id,
                timing_json=dumps(timer.payload()),
                stage="extracting",
                progress=25,
            )

            audio_path = settings.resolve_job_audio_path(job.id, job.audio_path)
            app_settings = load_settings(db)
            try:
                max_seconds = int(app_settings.capture_seconds or "0")
            except ValueError:
                max_seconds = 180
            # 16kHz mono s16le 约 32KB/秒；短于 8 分钟的旧样例在全长任务里要重抽
            stale_short_sample = audio_path.exists() and max_seconds == 0 and audio_path.stat().st_size < 16_000_000
            if not audio_path.exists() or audio_path.stat().st_size == 0 or stale_short_sample:
                raise_if_cancelled()
                self.extractor.extract_audio(
                    resolved.media_url,
                    audio_path,
                    extra_headers=resolved.headers,
                    max_seconds=max_seconds or None,
                )
            timer.stop("extracting")
            raise_if_cancelled()
            timer.start("transcribing")
            self._update(db, job, audio_path=str(audio_path), timing_json=dumps(timer.payload()), stage="transcribing", progress=50)

            segments = self.transcriber.transcribe(audio_path, app_settings)
            timer.stop("transcribing")
            raise_if_cancelled()
            self._update(
                db,
                job,
                transcript_json=dumps([item.model_dump() for item in segments]),
                timing_json=dumps(timer.payload()),
            )
            segments = self._maybe_ai_proofread(db, job, segments, app_settings, timer)
            timer.start("summarizing")
            self._update(
                db,
                job,
                transcript_json=dumps([item.model_dump() for item in segments]),
                timing_json=dumps(timer.payload()),
                stage="summarizing",
                progress=75,
            )

            summary = self.summarizer.summarize(segments, app_settings)
            timer.stop("summarizing")
            raise_if_cancelled()
            self._update(
                db,
                job,
                summary_json=summary.model_dump_json(),
                timing_json=dumps(timer.payload()),
                status="done",
                stage="done",
                progress=100,
            )
        except JobCancelled:
            job = db.get(Job, job_id)
            if job is not None and job.status not in {"cancelled", "done"}:
                self._update(db, job, status="cancelled", stage="cancelled", error="已取消")
        except (MediaError, TranscribeError, SummarizeError, RuntimeError) as exc:
            job = db.get(Job, job_id)
            if job is not None and job.status != "cancelled":
                self._update(db, job, status="failed", error=str(exc), progress=max(job.progress, 0))
        except Exception as exc:
            job = db.get(Job, job_id)
            if job is not None and job.status != "cancelled":
                self._update(db, job, status="failed", error=f"未预期错误：{exc}")


_pipeline: Pipeline | None = None


def get_pipeline() -> Pipeline:
    global _pipeline
    if _pipeline is None:
        _pipeline = Pipeline()
    return _pipeline


def set_pipeline(pipeline: Pipeline | None) -> None:
    global _pipeline
    _pipeline = pipeline
