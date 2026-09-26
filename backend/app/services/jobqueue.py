"""转写任务的排队执行。

批量创建时一次丢进很多任务，如果每个任务各起一个线程并行跑本机转写，
CPU 被摊薄，单个任务反而要等很久。这里统一走一条先进先出的队伍：

- 本机转写（SenseVoice / faster-whisper / 指向本机地址的接口）同一时刻只跑一个，而且是「整台机器」
  只跑一个：除了进程内排队，本机转写还额外拿一把跨进程文件锁（`settings.transcribe_lock_path()`），
  同一台机器上就算活着两个后端进程（`--reload` 换子进程时旧子进程还在跑原生转写没退干净、
  或手动起了两个），抢不到锁的那个也排队等着，不会两边各跑一个；
- 云端接口可以并行，路数取设置页「并行转写数」，留空（0）时用
  `TRANSCRIBE_CONCURRENCY`（默认 3 路），不受那把锁影响。

排在后面的任务保持 pending / stage=queued（界面显示「排队中」），轮到它时才记开始时间
再交给流水线，排队等待的时间不算进任务耗时。
"""

from __future__ import annotations

import os
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.models import Job, stamp_job_start
from app.schemas import AppSettingsOut
from app.services.pipeline import get_pipeline
from app.services.settings_store import load_settings, parse_transcribe_concurrency
from app.services.transcribe import is_local_transcribe

try:  # POSIX 上有 flock；没有这个模块的平台（Windows）只靠进程内排队
    import fcntl
except ImportError:  # pragma: no cover - Windows
    fcntl = None

MAX_WORKERS = 8
IDLE_WAIT = 0.2
GATE_WAIT = 0.05


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


def _pid_alive(pid: int | None) -> bool:
    """这个进程号还在不在。

    进程号被别的程序复用、或探不了活（Windows 的 `os.kill` 是另一套语义）都当它活着：
    宁可少回收几个，也不要把别的进程正在跑的任务抢回来重跑一遍。
    """
    if not pid or pid <= 0:
        return False
    if sys.platform == "win32":
        return True
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except (OSError, ValueError, OverflowError):
        return True
    return True


def reclaim_running(db: Session) -> int:
    """启动时把上个进程没跑完的任务放回队列（自己认领回来重新排队）。

    进程被强杀 / 崩溃（开发时 `--reload` 换子进程，旧子进程还在跑原生转写没退干净）时，
    任务会留在 `running`：界面上永远显示「转写中」，看着像还在跑，甚至像两个任务在同时转写。
    这里按 `Job.owner_pid` 认领：跑它的进程已经没了、或者就是本进程重启前的自己才收回；
    别的进程还活着就不动——那说明它真的还在跑，抢回来会变成两个任务一起处理同一段音频。
    """
    mine = os.getpid()
    rows = db.query(Job).filter(Job.status == "running").all()
    stale = [job for job in rows if job.owner_pid in (None, mine) or not _pid_alive(job.owner_pid)]
    for job in stale:
        job.status = "pending"
        job.stage = "queued"
        job.progress = 0
        job.error = ""
        job.owner_pid = None
    if stale:
        db.commit()
    return len(stale)


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


def _gate_path() -> Path:
    return settings.transcribe_lock_path()


def _take_gate() -> int | None:
    """试着独占「本机转写」这把全机器唯一的锁；别的进程正占着就返回 None。

    返回的整数是文件描述符，-1 表示「这平台上没有 flock / 锁文件建不出来」，当成拿到了但不用释放。
    """
    if fcntl is None:
        return -1
    path = _gate_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handle = os.open(path, os.O_CREAT | os.O_RDWR, 0o644)
    except OSError:
        return -1  # 目录只读之类的问题别把任务卡死，退回进程内排队
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(handle)
        return None
    return handle


def _release_gate(handle: int | None) -> None:
    if handle is None or handle < 0:
        return
    try:
        fcntl.flock(handle, fcntl.LOCK_UN)
    except OSError:
        pass
    os.close(handle)


def _wait_gate(generation: int) -> int | None:
    """等别的进程把本机转写跑完；停机 / 换代次时不再干等，返回 None 让调用方把任务放回队列。"""
    while True:
        handle = _take_gate()
        if handle is not None:
            return handle
        if _stop.is_set() or generation != _generation:
            return None
        time.sleep(GATE_WAIT)


def _serial_local() -> bool:
    """当前是不是「本机转写」的 1 路模式（只有这种模式才需要抢跨进程闸门）。"""
    with _lock:
        return _concurrency <= 1


def _put_back(item: _Item) -> None:
    """抢不到闸门又赶上停机 / 换代次时，把任务放回队头，交给下一批线程接着排。"""
    with _lock:
        if item.job_id:
            _queued_ids.add(item.job_id)
        _items.insert(0, item)
    _wake.set()


def _loop(generation: int) -> None:
    # 代次对不上说明这批线程已经被 stop_worker() 换掉（哪怕手上那个任务还没跑完），自己退出，
    # 免得重启后同时存在两批工作线程又把转写跑成并行。
    while not _stop.is_set() and generation == _generation:
        item = _take()
        if item is None:
            _wake.wait(IDLE_WAIT)
            _wake.clear()
            continue
        _run(item, generation)


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


def _run(item: _Item, generation: int) -> None:
    global _active
    gate: int | None = None
    try:
        if _serial_local():
            # 本机转写：整台机器同一时刻只跑一个，别的进程在跑就先等它（等不到就放回队列）
            gate = _wait_gate(generation)
            if gate is None:
                _put_back(item)
                return
        _mark_started(item.job_id)
        item.run()
    except Exception:
        pass  # 单个任务出错不能让队列停摆（失败状态由流水线自己写）
    finally:
        _release_gate(gate)
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
