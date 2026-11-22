"""Short-lived signed access links delivered only in an owner's private room."""
import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from pathlib import Path

LOCAL = Path(os.getenv(
    "ROCKETCHAT_LOCAL_PATH",
    Path(__file__).resolve().parents[3] / "rocketchat" / ".local",
))


def signing_key(path=None):
    path = Path(path or LOCAL / "review-link.key")
    try:
        return path.read_bytes()
    except FileNotFoundError:
        path.parent.mkdir(parents=True, exist_ok=True)
        value = secrets.token_bytes(32)
        try:
            handle = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(handle, "wb") as stream:
                stream.write(value)
            return value
        except FileExistsError:
            return path.read_bytes()


def _encode(value):
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _decode(value):
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def issue_link(entity, *, lifetime=900, now=None, key_path=None):
    payload = {"draft": entity.id, "user": entity.author_id, "room": entity.room_id,
               "exp": int(now or time.time()) + lifetime}
    body = _encode(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
    signature = _encode(hmac.new(signing_key(key_path), body.encode(), hashlib.sha256).digest())
    return body + "." + signature


def verify_link(token, *, now=None, key_path=None):
    if not isinstance(token, str) or len(token) > 1200 or token.count(".") != 1:
        raise ValueError("invalid access link")
    body, supplied = token.split(".")
    expected = _encode(hmac.new(signing_key(key_path), body.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(supplied, expected):
        raise ValueError("invalid access link")
    payload = json.loads(_decode(body))
    if set(payload) != {"draft", "user", "room", "exp"} or not all(
            isinstance(payload[k], str) for k in ("draft", "user", "room")):
        raise ValueError("invalid access link")
    current = int(now or time.time())
    if payload["exp"] < current or payload["exp"] > current + 1800:
        raise ValueError("expired access link")
    return payload


def issue_manager_link(user_id: str, username: str, *, lifetime=300, now=None, key_path=None):
    payload = {"purpose": "manager-dashboard", "user": user_id, "username": username,
               "exp": int(now or time.time()) + lifetime}
    body = _encode(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
    signature = _encode(hmac.new(signing_key(key_path), body.encode(), hashlib.sha256).digest())
    return body + "." + signature


def verify_manager_link(token, *, now=None, key_path=None):
    if not isinstance(token, str) or len(token) > 1200 or token.count(".") != 1:
        raise ValueError("invalid manager access link")
    body, supplied = token.split(".")
    expected = _encode(hmac.new(signing_key(key_path), body.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(supplied, expected):
        raise ValueError("invalid manager access link")
    payload = json.loads(_decode(body))
    if set(payload) != {"purpose", "user", "username", "exp"} or payload["purpose"] != "manager-dashboard":
        raise ValueError("invalid manager access link")
    if not isinstance(payload["user"], str) or not isinstance(payload["username"], str):
        raise ValueError("invalid manager access link")
    current = int(now or time.time())
    if payload["exp"] < current or payload["exp"] > current + 600:
        raise ValueError("expired manager access link")
    return payload


def issue_session(user_id: str, username: str, room_id: str, *, purpose="review-session",
                  lifetime=900, now=None, key_path=None):
    """Create an app-only session; it is never a Rocket.Chat auth token."""
    payload = {"purpose": purpose, "user": user_id, "username": username,
               "room": room_id, "exp": int(now or time.time()) + lifetime}
    body = _encode(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
    signature = _encode(hmac.new(signing_key(key_path), body.encode(), hashlib.sha256).digest())
    return body + "." + signature


def verify_session(token, *, purpose="review-session", now=None, key_path=None):
    if not isinstance(token, str) or len(token) > 1200 or token.count(".") != 1:
        raise ValueError("invalid app session")
    body, supplied = token.split(".")
    expected = _encode(hmac.new(signing_key(key_path), body.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(supplied, expected):
        raise ValueError("invalid app session")
    payload = json.loads(_decode(body))
    if set(payload) != {"purpose", "user", "username", "room", "exp"} or payload["purpose"] != purpose:
        raise ValueError("invalid app session")
    if not all(isinstance(payload[key], str) for key in ("user", "username", "room")):
        raise ValueError("invalid app session")
    current = int(now or time.time())
    if payload["exp"] < current or payload["exp"] > current + 1800:
        raise ValueError("expired app session")
    return payload
