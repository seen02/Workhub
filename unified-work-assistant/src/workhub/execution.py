"""Request-local reads and content-free timings; never a cross-request ACL cache."""
import copy
import functools
import inspect
import json
import logging
import time
import uuid
from contextlib import contextmanager, nullcontext
from contextvars import ContextVar

current = ContextVar('workhub_execution', default=None)
log = logging.getLogger('workhub.performance')


def count(name):
    state = current.get()
    if state is not None:
        counters = state['metrics']['counts']
        counters[name] = counters.get(name, 0) + 1


@contextmanager
def span(name):
    start = time.monotonic()
    count(name)
    try:
        yield
    finally:
        state = current.get()
        if state is not None:
            timings = state['metrics']['seconds']
            timings[name] = timings.get(name, 0) + time.monotonic() - start


def invalidate():
    from . import permissions
    state = current.get()
    if state is not None:
        state['reads'].clear()
    snapshots = permissions.request_snapshots.get()
    if snapshots is not None:
        snapshots.clear()


@contextmanager
def fresh():
    """New read phase, including ACL/name caches. Never restore stale snapshots."""
    invalidate()
    try:
        yield
    finally:
        invalidate()


@contextmanager
def request(name, user=None, wait_seconds=0):
    from . import permissions
    parent = current.get()
    actor = None if user is None else (user.get('sub'), user.get('email'), bool(user.get('admin')))
    if parent is not None and parent['actor'] == actor:
        yield parent
        return
    metrics = parent['metrics'] if parent else {'id': uuid.uuid4().hex, 'counts': {}, 'seconds': {}}
    state = {'actor': actor, 'reads': {}, 'metrics': metrics}
    token = current.set(state)
    acl_token = permissions.request_snapshots.set({})
    start = time.monotonic()
    outcome = 'ok'
    if wait_seconds:
        metrics['seconds']['queue_wait'] = max(0, wait_seconds)
    try:
        yield state
    except BaseException:
        outcome = 'error'
        raise
    finally:
        permissions.request_snapshots.reset(acl_token)
        current.reset(token)
        # A nested actor scope must not leave pre-mutation data in its caller.
        invalidate()
        if parent is None:
            payload = {**metrics, 'operation': name, 'outcome': outcome,
                       'elapsed_seconds': round(time.monotonic() - start, 4)}
            payload['seconds'] = {k: round(v, 4) for k, v in metrics['seconds'].items()}
            log.info('request_metrics %s', json.dumps(payload, separators=(',', ':')))


def operation(name, *, refresh=False, actor=True):
    def decorate(fn):
        @functools.wraps(fn)
        def wrapped(*args, **kwargs):
            user = (args[0] if args else kwargs.get('user')) if actor else None
            with request(name, user), (fresh() if refresh else nullcontext()), span(name):
                return fn(*args, **kwargs)
        return wrapped
    return decorate


def measured(name):
    def decorate(fn):
        if inspect.iscoroutinefunction(fn):
            @functools.wraps(fn)
            async def asynchronous(*args, **kwargs):
                with span(name):
                    return await fn(*args, **kwargs)
            return asynchronous
        @functools.wraps(fn)
        def synchronous(*args, **kwargs):
            with span(name):
                return fn(*args, **kwargs)
        return synchronous
    return decorate


def read(key, loader, label):
    state = current.get()
    if state is None:
        return loader()
    if key in state['reads']:
        count('cache_hit.' + label)
        return copy.deepcopy(state['reads'][key])
    value = loader()  # Failures and missing documents are not reusable results.
    if value is not None:
        state['reads'][key] = copy.deepcopy(value)
    return value
