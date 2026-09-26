import os
import threading
import time
from datetime import datetime, timedelta

import pytest
from sqlalchemy.orm import sessionmaker

from app.models import Job
from app.services import jobqueue


class RecordingPipeline:
    """记录每个任务的起止，用来看队列是不是一个一个跑的。"""

    def __init__(self, delay: float = 0.02, barrier: threading.Barrier | None = None) -> None:
        self.delay = delay
        self.barrier = barrier
        self.events: list[tuple[str, str]] = []
        self.active = 0
        self.peak = 0
        self._lock = threading.Lock()

    def run_job(self, job_id: str) -> None:
        with self._lock:
            self.active += 1
            self.peak = max(self.peak, self.active)
        self.events.append(("start", job_id))
        if self.barrier is not None:
            # 只有真的同时在跑才能一起过闸；串行时这里会超时，任务自然拿不到 end
            self.barrier.wait(timeout=2)
        time.sleep(self.delay)
        self.events.append(("end", job_id))
        with self._lock:
            self.active -= 1

    def retranscribe_job(self, job_id: str, continue_after: bool = True) -> None:
        self.run_job(job_id)


@pytest.fixture
def queue():
    jobqueue.stop_worker()  # 顺手清掉别的用例留在队列里的任务
    jobqueue.set_concurrency(1)  # 默认本机串行；要测云端并行的用例自己调高
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


def _wait_digest(pipeline: RecordingPipeline) -> None:
    deadline = time.time() + 3
    while time.time() < deadline:
        if any(item[0] == "digest" for item in pipeline.events):
            return
        time.sleep(0.01)
    raise AssertionError(f"汇总没跑起来：{pipeline.events}")


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
    monkeypatch.setattr("app.services.digest.run_schedule_digest", lambda log_id: ran.append(("digest", log_id)))
    schedule._execute_jobs(["s1", "s2"], digest_log_id="log-1")
    assert pipeline.events == []  # 投进队列就返回，不在请求线程里跑
    assert queue.queued_job_ids() == ["s1", "s2"]  # 整批拆成一个个任务排队，汇总另算一项
    queue.start_worker()
    _wait_done(pipeline, 2)
    assert pipeline.events == [
        ("start", "s1"),
        ("end", "s1"),
        ("start", "s2"),
        ("end", "s2"),
    ]
    assert ran == [("digest", "log-1")]


def test_schedule_digest_waits_for_the_whole_batch(queue, monkeypatch):
    from app.services import schedule

    pipeline = RecordingPipeline(delay=0.05)
    monkeypatch.setattr(jobqueue, "get_pipeline", lambda: pipeline)
    monkeypatch.setattr(
        "app.services.digest.run_schedule_digest",
        lambda log_id: pipeline.events.append(("digest", log_id)),
    )
    queue.set_concurrency(3)  # 云端接口：两个任务并行跑
    schedule._execute_jobs(["s1", "s2"], digest_log_id="log-1")
    queue.start_worker()
    _wait_done(pipeline, 2)
    _wait_digest(pipeline)
    assert pipeline.events.count(("digest", "log-1")) == 1
    assert pipeline.events[-1] == ("digest", "log-1")  # 汇总排在整批任务后面


def test_forget_releases_digest_wait(queue, monkeypatch):
    from app.services import schedule

    ran: list[tuple[str, str]] = []
    monkeypatch.setattr("app.services.digest.run_schedule_digest", lambda log_id: ran.append(("digest", log_id)))
    schedule._execute_jobs(["s1"], digest_log_id="log-1")
    queue.forget("s1")  # 任务取消 / 删掉后，汇总不该一直等它
    queue.start_worker()
    deadline = time.time() + 3
    while time.time() < deadline and not ran:
        time.sleep(0.01)
    assert ran == [("digest", "log-1")]


def test_cloud_concurrency_runs_jobs_together(queue, queue_db, monkeypatch):
    jobs = [_job(queue_db, f"云端{index}") for index in range(1, 4)]
    pipeline = RecordingPipeline(delay=0.05, barrier=threading.Barrier(3))
    monkeypatch.setattr(jobqueue, "get_pipeline", lambda: pipeline)
    queue.set_concurrency(3)  # 云端接口：3 路并行
    for job in jobs:
        queue.enqueue_job(job.id)
    queue.start_worker()
    _wait_done(pipeline, len(jobs))
    assert pipeline.peak == 3  # 三个任务真的同时在跑
    assert sorted(item[1] for item in pipeline.events if item[0] == "start") == sorted(job.id for job in jobs)


def _app_settings(**overrides):
    from app.schemas import AppSettingsOut

    data = {
        "transcribe_model": "",
        "transcribe_api_key": "",
        "transcribe_base_url": "",
        "transcribe_concurrency": 0,
    }
    data.update(overrides)
    return AppSettingsOut(**data)


def test_is_local_transcribe_flags_local_sources():
    from app.services.transcribe import is_local_transcribe

    assert is_local_transcribe(_app_settings(transcribe_model="sensevoice-small-q8")) is True
    assert is_local_transcribe(_app_settings(transcribe_model="large-v3")) is True
    assert is_local_transcribe(_app_settings(transcribe_model="whisper-1")) is True  # 没配 Key 会退回本机 SenseVoice
    assert is_local_transcribe(_app_settings(transcribe_model="", transcribe_api_key="sk")) is False
    cloud = {"transcribe_model": "whisper-1", "transcribe_api_key": "sk"}
    assert is_local_transcribe(_app_settings(**cloud)) is False
    assert is_local_transcribe(_app_settings(**cloud, transcribe_base_url="http://localhost:9000/v1")) is True


def test_resolve_concurrency_keeps_local_transcribe_serial(queue):
    # 本机模型：SenseVoice、faster-whisper、以及没配 Key / 指向本机地址的接口，一律串行
    assert queue.resolve_concurrency(_app_settings(transcribe_model="sensevoice-small-q8")) == 1
    assert queue.resolve_concurrency(_app_settings(transcribe_model="small")) == 1
    assert queue.resolve_concurrency(_app_settings(transcribe_model="whisper-1")) == 1
    assert (
        queue.resolve_concurrency(
            _app_settings(
                transcribe_model="whisper-1",
                transcribe_api_key="sk-test",
                transcribe_base_url="http://127.0.0.1:9000/v1",
            )
        )
        == 1
    )


def test_resolve_concurrency_lets_cloud_run_parallel(queue):
    cloud = {
        "transcribe_model": "whisper-1",
        "transcribe_api_key": "sk-test",
        "transcribe_base_url": "https://api.openai.com/v1",
    }
    assert queue.resolve_concurrency(_app_settings(**cloud)) == 3  # 自动：用 TRANSCRIBE_CONCURRENCY
    assert queue.resolve_concurrency(_app_settings(**cloud, transcribe_concurrency=4)) == 4
    assert queue.resolve_concurrency(_app_settings(**cloud, transcribe_concurrency=99)) == 8
    assert queue.concurrency() == 1  # 只算不发号，队列并行数没被动过


def test_refresh_concurrency_follows_saved_settings(queue, db_session):
    from app.services.settings_store import save_settings

    save_settings(
        db_session,
        {
            "transcribe_model": "whisper-1",
            "transcribe_api_key": "sk-test",
            "transcribe_base_url": "https://api.openai.com/v1",
            "transcribe_concurrency": 4,
        },
    )
    assert queue.refresh_concurrency(db_session) == 4
    assert queue.concurrency() == 4
    save_settings(db_session, {"transcribe_model": "sensevoice-small-q8"})  # 换回本机就退回串行
    assert queue.refresh_concurrency(db_session) == 1
    assert queue.concurrency() == 1


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


def _wait_started(pipeline: RecordingPipeline, count: int) -> None:
    deadline = time.time() + 3
    while time.time() < deadline:
        if len([item for item in pipeline.events if item[0] == "start"]) >= count:
            return
        time.sleep(0.01)
    raise AssertionError(f"队列没把任务跑起来：{pipeline.events}")


def test_two_retry_batches_share_the_same_queue(client, queue, queue_db, monkeypatch):
    """两批多选重试也要排在同一条队里：后一批提交时前一批还在转写，就得等它跑完（本机固定 1 路）。"""
    first = [_job(queue_db, f"第一批{index}", status="failed", stage="failed") for index in range(2)]
    pipeline = RecordingPipeline(delay=0.2)
    monkeypatch.setattr(jobqueue, "get_pipeline", lambda: pipeline)
    queue.start_worker()
    assert client.post("/api/jobs/batch", json={"action": "retry", "ids": [job.id for job in first]}).status_code == 200
    _wait_started(pipeline, 1)  # 第一批已经在转写了
    second = [_job(queue_db, f"第二批{index}", status="failed", stage="failed") for index in range(2)]
    assert client.post("/api/jobs/batch", json={"action": "retry", "ids": [job.id for job in second]}).status_code == 200
    # 第二批提交进来时，第一批还没跑完：第二批只在队列里等着，不该同时开跑
    assert pipeline.peak == 1
    _wait_done(pipeline, 4)
    assert pipeline.peak == 1  # 全程都只有一个在跑
    assert [item[1] for item in pipeline.events if item[0] == "start"] == [
        job.id for job in first + second
    ]  # 先来后到：第一批跑完才轮到第二批
    assert queue.queued_job_ids() == []


def test_local_transcribe_waits_for_the_gate_held_by_another_process(queue, queue_db, monkeypatch):
    """整台机器只允许一个本机转写：别的进程（--reload 的旧子进程等）占着闸门时得等着，不许抢。"""
    if jobqueue.fcntl is None:
        pytest.skip("这个平台没有 flock")
    pipeline = RecordingPipeline()
    monkeypatch.setattr(jobqueue, "get_pipeline", lambda: pipeline)
    held = jobqueue._take_gate()  # 假装另一个后端进程正在跑本机转写
    assert held is not None and held >= 0
    job = _job(queue_db, "等闸门")
    queue.enqueue_job(job.id)
    queue.start_worker()
    time.sleep(0.3)
    assert pipeline.events == []  # 闸门没放，任务跑不起来
    assert _read(queue_db, job.id).status == "pending"  # 等着的时候也不算开始
    jobqueue._release_gate(held)
    _wait_done(pipeline, 1)
    assert pipeline.events == [("start", job.id), ("end", job.id)]


def test_cloud_parallel_ignores_the_gate(queue, queue_db, monkeypatch):
    """闸门只管本机转写：云端接口按「并行转写数」并行，不被别的进程的锁挡住。"""
    if jobqueue.fcntl is None:
        pytest.skip("这个平台没有 flock")
    queue.set_concurrency(3)
    pipeline = RecordingPipeline(delay=0.2)
    monkeypatch.setattr(jobqueue, "get_pipeline", lambda: pipeline)
    held = jobqueue._take_gate()
    assert held is not None and held >= 0
    try:
        for index in range(2):
            queue.enqueue_job(_job(queue_db, f"云端{index}").id)
        queue.start_worker()
        _wait_done(pipeline, 2)
    finally:
        jobqueue._release_gate(held)
    assert pipeline.peak == 2  # 两路并行，没被闸门挡住


def test_startup_reclaims_running_jobs_left_by_a_dead_process(queue, queue_db):
    """上个进程被强杀留下的「转写中」：启动时放回队列重新排队，不再永远挂着。"""
    stale = _job(queue_db, "被强杀了", status="running", stage="transcribing")
    stale.owner_pid = 3_000_000  # 系统里用不到的进程号
    stale.progress = 50
    queue_db.commit()
    assert queue.reclaim_running(queue_db) == 1
    fresh = _read(queue_db, stale.id)
    assert (fresh.status, fresh.stage, fresh.progress, fresh.owner_pid) == ("pending", "queued", 0, None)
    assert queue.requeue_pending(queue_db) == 1
    assert queue.queued_job_ids() == [stale.id]


def test_startup_keeps_running_jobs_owned_by_a_live_process(queue, queue_db):
    """跑它的进程还活着就别动：那说明任务真的还在跑，抢回来会变成两个任务一起处理同一段音频。"""
    running = _job(queue_db, "别的进程在跑", status="running", stage="transcribing")
    running.owner_pid = os.getppid()
    queue_db.commit()
    assert queue.reclaim_running(queue_db) == 0
    assert _read(queue_db, running.id).status == "running"
