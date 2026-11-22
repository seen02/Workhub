"""Process-owned synchronous service clients; per-call credentials, no auth cache."""
import atexit
import threading
import httpx
from . import execution

_clients = {}
_lock = threading.Lock()


def client(service):
    with _lock:
        if service not in _clients:
            _clients[service] = httpx.Client(limits=httpx.Limits(
                max_connections=16, max_keepalive_connections=8, keepalive_expiry=30))
        return _clients[service]


def request(service, method, url, *, metric, **kwargs):
    # These APIs authenticate through explicit headers, never pooled cookies.
    c = client(service)
    req = c.build_request(method, url, **kwargs)
    req.headers.pop('cookie', None)
    with execution.span('http.' + service + '.' + metric):
        return c.send(req)


def close():
    with _lock:
        clients = list(_clients.values())
        _clients.clear()
    for c in clients:
        c.close()


atexit.register(close)
