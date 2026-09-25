"""转写任务的排队执行。

批量创建时一次丢进很多任务，如果每个任务各起一个线程并行跑本机转写，
CPU 被摊薄，单个任务反而要等很久。这里统一走一条先进先出的队伍：

- 本机转写（SenseVoice / faster-whisper / 指向本机地址的接口）同一时刻只跑一个；
- 云端接口可以并行，路数取设置页「并行转写数」，留空（0）时用
  `TRANSCRIBE_CONCURRENCY`（默认 3 路）。

排在后面的任务保持 pending / stage=queued（界面显示「排队中」），轮到它时才记开始时间
再交给流水线，排队等待的时间不算进任务耗时。
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Callable, Iterable

from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.models import Job, stamp_job_start
from app.schemas import AppSettingsOut
from app.services.pipeline import get_pipeline
from app.services.settings_store import load_settings, parse_transcribe_concurrency
from app.services.transcribe import is_local_transcribe

MAX_WORKERS = 8
IDLE_WAIT = 0.2


@dataclass
class _Item:
    job_id: str
    run: Callable[[], None]
    depends_on: frozenset[str] = frozenset()


_items: list[_Item] = []
_queued_ids: set[str] = set()
# 排队中 + 正在跑的任务：等它们的汇总项要等这些都跑完才轮到
_unfinished: set[str] = set()
_running_ids: set[str] = set()
_active = 0
_concurrency = 1
_lock = threading.Lock()
_wake = threading.Event()
_stop = threading.Event()
_threads: list[threading.Thread] = []
_generation = 0


def enqueue(job_id: str, run: Callable[[], None], depends_on: Iterable[str] = ()) -> None:
    """排到队尾。同一个任务重复提交只留一次（重试连点不会排两遍）。

    job_id 留空表示整批算一项（比如定时批次的汇总总结），用 depends_on 指定要等哪些任务
    跑完才轮到它；被等的那几个任务取消 / 删掉后这份等待会直接放行。
    """
    deps = frozenset(item for item in depends_on if item)
    with _lock:
        if job_id:
            if job_id in _queued_ids:
                return
            _queued_ids.add(job_id)
            _unfinished.add(job_id)
        _items.append(_Item(job_id=job_id, run=run, depends_on=deps))
    _wake.set()


def enqueue_job(job_id: str) -> None:
    """排队跑整条流水线（新建 / 重试 / 汇总任务走这里）。"""
    enqueue(job_id, lambda: get_pipeline().run_job(job_id))


def enqueue_retranscribe(job_id: str, continue_after: bool = True) -> None:
    """排队重跑转写；continue_after=False 时只重转写，不接着校对和总结。"""
    enqueue(job_id, lambda: get_pipeline().retranscribe_job(job_id, continue_after))


def forget(job_id: str) -> None:
    """任务被取消 / 删除后从队列里摘掉，别白占一个位置，也别让等它的汇总卡住。"""
    if not job_id:
        return
    with _lock:
        _queued_ids.discard(job_id)
        _unfinished.discard(job_id)
        _items[:] = [item for item in _items if item.job_id != job_id]
    _wake.set()


def queued_job_ids() -> list[str]:
    """还在排队的任务 id（按排队顺序）。"""
    with _lock:
        return [item.job_id for item in _items if item.job_id]


def running_job_ids() -> list[str]:
    """当前正在跑的任务 id，空闲时是空列表。"""
    with _lock:
        return sorted(_running_ids)


def concurrency() -> int:
    """当前允许同时跑几个任务。"""
    with _lock:
        return _concurrency


def set_concurrency(value: int) -> None:
    global _concurrency
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = 1
    with _lock:
        _concurrency = max(1, min(number, MAX_WORKERS))
    _wake.set()


def resolve_concurrency(app_settings: AppSettingsOut) -> int:
    """本机转写固定 1 路（并行只会互相抢 CPU）；云端接口按配置并行。

    设置里留空 / 0 表示自动，用 `TRANSCRIBE_CONCURRENCY`（默认 3 路）。
    """
    if is_local_transcribe(app_settings):
        return 1
    configured = parse_transcribe_concurrency(getattr(app_settings, "transcribe_concurrency", 0))
    return configured or max(1, min(int(settings.transcribe_concurrency), MAX_WORKERS))


def configure(app_settings: AppSettingsOut) -> int:
    """按设置调整并行路数（启动、保存设置时调用）。"""
    value = resolve_concurrency(app_settings)
    set_concurrency(value)
    return value


def refresh_concurrency(db: Session) -> int:
    """读一遍设置再调整并行路数；读不出来就沿用当前值。"""
    try:
        return configure(load_settings(db))
    except Exception:
        return concurrency()


def requeue_pending(db: Session) -> int:
    """启动时把上次没跑完、还停在 pending 的任务重新排队，否则界面会一直卡在「排队中」。"""
    rows = db.query(Job).filter(Job.status == "pending").order_by(Job.created_at.asc()).all()
    for job in rows:
        enqueue_job(job.id)
    return len(rows)


def start_worker() -> None:
    """启动转写工作线程（应用启动时调用）。线程按上限起，实际并行路数由 _concurrency 控制。"""
    global _threads, _generation
    _threads = [item for item in _threads if item.is_alive()]
    if _threads:
        return
    _generation += 1
    generation = _generation
    _stop.clear()
    _wake.clear()
    _threads = [
        threading.Thread(target=_loop, args=(generation,), name=f"job-queue-{index + 1}", daemon=True)
        for index in range(MAX_WORKERS)
    ]
    for thread in _threads:
        thread.start()


def stop_worker() -> None:
    """停掉工作线程并丢掉还没跑的任务（退出时用；这些任务下次启动会重新排队）。"""
    global _threads, _active
    _stop.set()
    _wake.set()
    current = threading.current_thread()
    for thread in _threads:
        if thread is not current and thread.is_alive():
            thread.join(timeout=2)
    _threads = []
    with _lock:
        _items.clear()
        _queued_ids.clear()
        _unfinished.clear()
        _running_ids.clear()
        _active = 0


def _loop(generation: int) -> None:
    # 代次对不上说明这批线程已经被 stop_worker() 换掉（哪怕手上那个任务还没跑完），自己退出，
    # 免得重启后同时存在两批工作线程又把转写跑成并行。
    while not _stop.is_set() and generation == _generation:
        item = _take()
        if item is None:
            _wake.wait(IDLE_WAIT)
            _wake.clear()
            continue
        _run(item)


def _take() -> _Item | None:
    """取下一个能跑的任务：并行路数没占满，且它要等的那批任务都已经跑完。"""
    global _active
    with _lock:
        if _active >= _concurrency:
            return None
        index = next(
            (index for index, item in enumerate(_items) if not item.depends_on & _unfinished),
            None,
        )
        if index is None:
            return None
        item = _items.pop(index)
        _queued_ids.discard(item.job_id)
        _active += 1
        if item.job_id:
            _running_ids.add(item.job_id)
    return item


def _run(item: _Item) -> None:
    global _active
    try:
        _mark_started(item.job_id)
        item.run()
    except Exception:
        pass  # 单个任务出错不能让队列停摆（失败状态由流水线自己写）
    finally:
        with _lock:
            _active -= 1
            if item.job_id:
                _running_ids.discard(item.job_id)
                _unfinished.discard(item.job_id)
        _wake.set()


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
