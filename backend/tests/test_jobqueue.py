import threading
import time
from datetime import datetime, timedelta

import pytest
from sqlalchemy.orm import sessionmaker

from app.models import Job
from app.services import jobqueue


class RecordingPipeline:
    """记录每个任务的起止，用来看队列是不是一个一个跑的。"""

    def __init__(self, delay: float = 0.02) -> None:
        self.delay = delay
        self.events: list[tuple[str, str]] = []
        self.active = 0
        self.peak = 0
        self._lock = threading.Lock()

    def run_job(self, job_id: str) -> None:
        with self._lock:
            self.active += 1
            self.peak = max(self.peak, self.active)
        self.events.append(("start", job_id))
        time.sleep(self.delay)
        self.events.append(("end", job_id))
        with self._lock:
            self.active -= 1

    def retranscribe_job(self, job_id: str, continue_after: bool = True) -> None:
        self.run_job(job_id)


@pytest.fixture
def queue():
    jobqueue.stop_worker()  # 顺手清掉别的用例留在队列里的任务
    yield jobqueue
    jobqueue.stop_worker()


@pytest.fixture
def queue_db(db_session, monkeypatch):
    """把队列用的 SessionLocal 指到测试库，队列才找得到测试里建的任务。"""
    monkeypatch.setattr(
        jobqueue,
        "SessionLocal",
        sessionmaker(bind=db_session.get_bind(), autoflush=False, autocommit=False),
    )
    return db_session


def _job(db, title: str, status: str = "pending", stage: str = "queued") -> Job:
    job = Job(title=title, source_url=f"https://example.com/{title}", status=status, stage=stage)
    db.add(job)
    db.commit()
    return job


def _read(db, job_id: str) -> Job:
    session = sessionmaker(bind=db.get_bind())()
    try:
        return session.get(Job, job_id)
    finally:
        session.close()


def _wait_done(pipeline: RecordingPipeline, count: int) -> None:
    deadline = time.time() + 3
    while time.time() < deadline:
        if len([item for item in pipeline.events if item[0] == "end"]) >= count:
            return
        time.sleep(0.01)
    raise AssertionError(f"队列没把任务跑完：{pipeline.events}")


def test_queue_runs_jobs_one_by_one(queue, queue_db, monkeypatch):
    jobs = [_job(queue_db, f"第{index}个") for index in range(1, 4)]
    pipeline = RecordingPipeline()
    monkeypatch.setattr(jobqueue, "get_pipeline", lambda: pipeline)
    for job in jobs:
        queue.enqueue_job(job.id)
    queue.start_worker()
    _wait_done(pipeline, len(jobs))
    expected: list[tuple[str, str]] = []
    for job in jobs:
        expected += [("start", job.id), ("end", job.id)]
    assert pipeline.events == expected  # 一个一个来，不重叠
    assert pipeline.peak == 1
    assert all(_read(queue_db, job.id).started_at is not None for job in jobs)  # 轮到自己才记开始时间


def test_queue_does_not_stamp_jobs_that_never_run(queue, queue_db, monkeypatch):
    gave_up = _job(queue_db, "已取消", status="cancelled", stage="cancelled")
    running = _job(queue_db, "正常")
    pipeline = RecordingPipeline()
    monkeypatch.setattr(jobqueue, "get_pipeline", lambda: pipeline)
    for job_id in (gave_up.id, "已经被删掉的任务", running.id):
        queue.enqueue_job(job_id)
    queue.start_worker()
    _wait_done(pipeline, 3)
    assert [item[1] for item in pipeline.events if item[0] == "start"] == [
        gave_up.id,
        "已经被删掉的任务",
        running.id,
    ]
    assert _read(queue_db, gave_up.id).started_at is None
    assert _read(queue_db, running.id).started_at is not None


def test_enqueue_keeps_same_job_once(queue):
    queue.enqueue_job("j1")
    queue.enqueue_job("j1")
    assert queue.queued_job_ids() == ["j1"]


def test_forget_drops_queued_job(queue):
    queue.enqueue_job("j1")
    queue.enqueue_job("j2")
    queue.forget("j1")
    assert queue.queued_job_ids() == ["j2"]


def test_requeue_pending_puts_unfinished_jobs_back(queue, db_session):
    began = datetime(2026, 1, 1, 8, 0, 0)
    queue.enqueue_job("old")  # 启动前的队列应当保持原样，重新排队排在它后面
    done = Job(title="已完成", source_url="https://example.com/a", status="done", stage="done")
    first = Job(
        title="排队一",
        source_url="https://example.com/b",
        status="pending",
        stage="queued",
        created_at=began,
    )
    second = Job(
        title="排队二",
        source_url="https://example.com/c",
        status="pending",
        stage="queued",
        created_at=began + timedelta(minutes=1),
    )
    db_session.add_all([done, first, second])
    db_session.commit()
    assert queue.requeue_pending(db_session) == 2
    assert queue.queued_job_ids() == ["old", first.id, second.id]


def test_schedule_batch_enters_the_same_queue(queue, monkeypatch):
    from app.services import schedule

    ran: list[tuple[str, str]] = []
    pipeline = RecordingPipeline()
    monkeypatch.setattr(jobqueue, "get_pipeline", lambda: pipeline)
    monkeypatch.setattr(schedule, "get_pipeline", lambda: pipeline)
    monkeypatch.setattr("app.services.digest.run_schedule_digest", lambda log_id: ran.append(("digest", log_id)))
    schedule._execute_jobs(["s1", "s2"], digest_log_id="log-1")
    assert pipeline.events == []  # 投进队列就返回，不在请求线程里跑
    queue.start_worker()
    _wait_done(pipeline, 2)
    assert pipeline.events == [
        ("start", "s1"),
        ("end", "s1"),
        ("start", "s2"),
        ("end", "s2"),
    ]
    assert ran == [("digest", "log-1")]


def test_create_job_goes_through_queue(client, queue):
    created = client.post(
        "/api/jobs",
        json={"source_url": "https://cdn.example.com/q.mp4", "title": "排队"},
    ).json()
    assert created["status"] == "pending"
    assert created["stage"] == "queued"
    assert created["id"] in queue.queued_job_ids()


def test_cancel_queued_job_drops_it_from_queue(client, queue):
    created = client.post(
        "/api/jobs",
        json={"source_url": "https://cdn.example.com/c.mp4", "title": "取消"},
    ).json()
    assert created["id"] in queue.queued_job_ids()
    cancelled = client.post(f"/api/jobs/{created['id']}/cancel").json()
    assert cancelled["status"] == "cancelled"
    assert created["id"] not in queue.queued_job_ids()
