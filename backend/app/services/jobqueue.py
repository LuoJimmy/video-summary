"""转写任务的排队执行。

批量创建时一次丢进很多任务，如果每个任务各起一个线程并行跑本机转写，
CPU 被摊薄，单个任务反而要等很久。这里改成单工作线程 FIFO：
同一时刻只有一个任务真正占用转写，排在后面的任务保持 pending / stage=queued
（界面显示「排队中」）；轮到它时才记开始时间再交给流水线，排队时间不算进任务耗时。
"""

from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass
from typing import Callable

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import Job, stamp_job_start
from app.services.pipeline import get_pipeline


@dataclass
class _Item:
    job_id: str
    run: Callable[[], None]


_items: deque[_Item] = deque()
_queued_ids: set[str] = set()
_running_id = ""
_lock = threading.Lock()
_wake = threading.Event()
_stop = threading.Event()
_thread: threading.Thread | None = None
_generation = 0
IDLE_WAIT = 0.2


def enqueue(job_id: str, run: Callable[[], None]) -> None:
    """排到队尾。同一个任务重复提交只留一次（重试连点不会排两遍）。

    job_id 留空表示整批算一项（定时任务一次触发创建的那批），不按任务去重、也不单独记开始时间。
    """
    with _lock:
        if job_id and job_id in _queued_ids:
            return
        if job_id:
            _queued_ids.add(job_id)
        _items.append(_Item(job_id=job_id, run=run))
    _wake.set()


def enqueue_job(job_id: str) -> None:
    """排队跑整条流水线（新建 / 重试 / 汇总任务走这里）。"""
    enqueue(job_id, lambda: get_pipeline().run_job(job_id))


def enqueue_retranscribe(job_id: str, continue_after: bool = True) -> None:
    """排队重跑转写；continue_after=False 时只重转写，不接着校对和总结。"""
    enqueue(job_id, lambda: get_pipeline().retranscribe_job(job_id, continue_after))


def forget(job_id: str) -> None:
    """任务被取消 / 删除后从队列里摘掉，别白占一个位置。"""
    global _items
    if not job_id:
        return
    with _lock:
        _queued_ids.discard(job_id)
        _items = deque(item for item in _items if item.job_id != job_id)


def queued_job_ids() -> list[str]:
    """还在排队的任务 id（按排队顺序）。"""
    with _lock:
        return [item.job_id for item in _items if item.job_id]


def running_job_id() -> str:
    """当前正在跑的任务 id，空闲时是空串。"""
    with _lock:
        return _running_id


def requeue_pending(db: Session) -> int:
    """启动时把上次没跑完、还停在 pending 的任务重新排队，否则界面会一直卡在「排队中」。"""
    rows = db.query(Job).filter(Job.status == "pending").order_by(Job.created_at.asc()).all()
    for job in rows:
        enqueue_job(job.id)
    return len(rows)


def start_worker() -> None:
    """启动唯一的转写工作线程（应用启动时调用）。"""
    global _thread, _generation
    if _thread is not None and _thread.is_alive():
        return
    _generation += 1
    generation = _generation
    _stop.clear()
    _wake.clear()
    _thread = threading.Thread(target=_loop, args=(generation,), name="job-queue", daemon=True)
    _thread.start()


def stop_worker() -> None:
    """停掉工作线程并丢掉还没跑的任务（退出时用；这些任务下次启动会重新排队）。"""
    global _thread
    _stop.set()
    _wake.set()
    thread = _thread
    if thread is not None and thread.is_alive():
        thread.join(timeout=2)
    _thread = None
    with _lock:
        _items.clear()
        _queued_ids.clear()


def _loop(generation: int) -> None:
    # 代次对不上说明这个线程已经被 stop_worker() 换掉（哪怕它手上那个任务还没跑完），自己退出，
    # 免得重启后同时存在两个工作线程又把转写跑成并行。
    while not _stop.is_set() and generation == _generation:
        item = _take()
        if item is None:
            _wake.wait(IDLE_WAIT)
            _wake.clear()
            continue
        _run(item)


def _take() -> _Item | None:
    global _running_id
    with _lock:
        if not _items:
            return None
        item = _items.popleft()
        _queued_ids.discard(item.job_id)
        _running_id = item.job_id
    return item


def _run(item: _Item) -> None:
    global _running_id
    try:
        _mark_started(item.job_id)
        item.run()
    except Exception:
        pass  # 单个任务出错不能让队列停摆（失败状态由流水线自己写）
    finally:
        with _lock:
            _running_id = ""


def _mark_started(job_id: str) -> None:
    """轮到真正开始跑时才记开始时间，排队等待的时间不算在任务耗时里。"""
    if not job_id:
        return
    db = SessionLocal()
    try:
        job = db.get(Job, job_id)
        if job is None or job.status == "cancelled":
            return
        stamp_job_start(job)
        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()
