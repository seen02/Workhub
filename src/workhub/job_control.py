"""Per-DM cancellation for read-only report preparation, independent of its queue."""
import asyncio
import threading
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar

current = ContextVar('report_job', default=None)
lock = threading.RLock()
active = {}
cutoffs = {}
TIME_LIMIT = 120


class Stopped(Exception):
    pass


class Job:
    def __init__(self, uid, room):
        self.key = (uid, room)
        self.id = uuid.uuid4().hex
        self.command = '긴급 취소 · ' + self.id
        self.cancelled = threading.Event()
        self.deadline = time.monotonic() + TIME_LIMIT


def check():
    job = current.get()
    if job:
        if job.cancelled.is_set():raise Stopped('보고 생성을 중단했어요.')
        if time.monotonic() >= job.deadline:
            raise Stopped('보고 생성이 2분을 넘어 자동 중단했어요. 업무와 진행 상태를 구체적으로 적어 다시 보내 주세요.')


@contextmanager
def running(uid, room, received=None):
    job = Job(uid, room)
    with lock:
        if discarded(uid, room, received):raise Stopped('대기 중이던 보고 생성을 취소했어요.')
        if job.key in active:raise ValueError('이미 보고를 정리하고 있어요. 긴급 취소 후 다시 입력해 주세요.')
        active[job.key] = job
    context = current.set(job)
    try:
        yield job
        with lock:check()
    finally:
        current.reset(context)
        with lock:
            if active.get(job.key) is job:active.pop(job.key)


def stop(uid, room, command, received):
    key = (uid, room)
    with lock:
        job = active.get(key)
        # A stale button must never cancel a newer request or another person's work.
        if command.startswith('긴급 취소 ·') and (not job or command != job.command):
            return '이미 끝났거나 취소된 작업의 버튼이에요.'
        if job:job.cancelled.set()
        cutoffs[key] = received
        return ('보고 생성 중단을 요청했어요. 이 대화에서 먼저 보낸 대기 요청도 취소했어요.' if job else
                '실행 중인 보고 생성은 없어요. 이 대화에서 먼저 보낸 대기 요청은 취소했어요.')


def discarded(uid, room, received):
    with lock:
        return received is not None and received <= cutoffs.get((uid, room), -1)


def has_active(uid, room):
    with lock:return (uid, room) in active


async def wait(awaitable):
    """Cancel and await the HTTP task, closing its socket instead of abandoning it."""
    if current.get() is None:return await awaitable
    task = asyncio.ensure_future(awaitable)
    try:
        while True:
            check()
            done, _ = await asyncio.wait({task}, timeout=.1)
            if done:
                check()
                return await task
    finally:
        if not task.done():task.cancel()
        await asyncio.gather(task, return_exceptions=True)
