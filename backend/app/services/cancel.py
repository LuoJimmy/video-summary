from __future__ import annotations

import threading
from contextlib import contextmanager
from contextvars import ContextVar
from subprocess import Popen
from typing import Iterator


class JobCancelled(Exception):
    def __init__(self, message: str = "任务已取消") -> None:
        super().__init__(message)


_current_job_id: ContextVar[str | None] = ContextVar("current_job_id", default=None)
_events: dict[str, threading.Event] = {}
_procs: dict[str, Popen] = {}
_lock = threading.Lock()


def current_job_id() -> str | None:
    return _current_job_id.get()


def request_cancel(job_id: str) -> None:
    with _lock:
        event = _events.setdefault(job_id, threading.Event())
        event.set()
        proc = _procs.get(job_id)
    if proc is not None and proc.poll() is None:
        proc.kill()


def is_cancelled(job_id: str | None = None) -> bool:
    jid = job_id or _current_job_id.get()
    if not jid:
        return False
    with _lock:
        event = _events.get(jid)
    return bool(event and event.is_set())


def raise_if_cancelled(job_id: str | None = None) -> None:
    if is_cancelled(job_id):
        raise JobCancelled()


def register_process(proc: Popen) -> None:
    jid = _current_job_id.get()
    if not jid:
        return
    with _lock:
        _procs[jid] = proc
        cancelled = bool(_events.get(jid) and _events[jid].is_set())
    if cancelled:
        proc.kill()
        raise JobCancelled()


def unregister_process() -> None:
    jid = _current_job_id.get()
    if not jid:
        return
    with _lock:
        _procs.pop(jid, None)


def clear_cancel(job_id: str) -> None:
    with _lock:
        _events.pop(job_id, None)
        _procs.pop(job_id, None)


@contextmanager
def job_scope(job_id: str) -> Iterator[None]:
    token = _current_job_id.set(job_id)
    with _lock:
        _events.setdefault(job_id, threading.Event())
    try:
        yield
    finally:
        _current_job_id.reset(token)
        clear_cancel(job_id)
