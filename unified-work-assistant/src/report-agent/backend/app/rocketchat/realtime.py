"""Authenticated Rocket.Chat room-message stream for low-request ingestion."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import queue
import threading
import time
from collections.abc import Callable, Iterable
from datetime import datetime, timezone
from urllib.parse import urlparse

from websockets.sync.client import connect

log = logging.getLogger("report_bot")


def normalize_message(message: dict) -> dict:
    """Normalize Meteor EJSON dates to the ISO strings used by the REST API."""
    normalized = dict(message)
    stamp = normalized.get("ts")
    if isinstance(stamp, dict) and "$date" in stamp:
        value = stamp["$date"]
        if isinstance(value, (int, float)):
            normalized["ts"] = datetime.fromtimestamp(value / 1000, timezone.utc).isoformat().replace("+00:00", "Z")
        elif isinstance(value, str):
            normalized["ts"] = value
    return normalized


def room_message(frame: dict, room_ids: set[str]) -> dict | None:
    """Extract one allowlisted room message from a Rocket.Chat DDP event."""
    if frame.get("msg") != "changed" or frame.get("collection") != "stream-room-messages":
        return None
    fields = frame.get("fields") or {}
    args = fields.get("args") or []
    message = args[0] if args and isinstance(args[0], dict) else None
    if not message or message.get("rid") not in room_ids:
        return None
    return normalize_message(message)


class RoomMessageStream:
    """Keep scoped room subscriptions and add newly discovered report rooms safely."""

    def __init__(self, url: str, username: str, password: str, room_ids: Iterable[str],
                 on_message: Callable[[dict], None], reconnect_seconds: float = 3.0):
        parsed = urlparse(url)
        allowed_hosts = {"127.0.0.1", "localhost"}
        internal_host = urlparse(os.getenv("ROCKETCHAT_INTERNAL_URL", "")).hostname
        if internal_host:
            allowed_hosts.add(internal_host)
        if parsed.hostname not in allowed_hosts:
            raise ValueError("이 개발용 실시간 연결은 로컬 Rocket.Chat만 허용합니다.")
        scheme = "wss" if parsed.scheme == "https" else "ws"
        self.url = f"{scheme}://{parsed.netloc}/websocket"
        self.username = username
        self.password_digest = hashlib.sha256(password.encode()).hexdigest()
        self.room_ids = set(room_ids)
        self._room_lock = threading.Lock()
        self._new_rooms = queue.SimpleQueue()
        self.on_message = on_message
        self.reconnect_seconds = reconnect_seconds
        self.connected = threading.Event()
        self._stopped = threading.Event()

    def start(self) -> threading.Thread:
        thread = threading.Thread(target=self.run_forever, name="rocket-chat-stream", daemon=True)
        thread.start()
        return thread

    def stop(self) -> None:
        self._stopped.set()

    def add_room(self, room_id: str) -> bool:
        """Queue a room subscription without reconnecting the WebSocket."""
        with self._room_lock:
            if room_id in self.room_ids:
                return False
            self.room_ids.add(room_id)
        self._new_rooms.put(room_id)
        return True

    @staticmethod
    def _send(ws, payload: dict) -> None:
        ws.send(json.dumps(payload, separators=(",", ":")))

    def _receive(self, ws, timeout=70) -> dict:
        while True:
            frame = json.loads(ws.recv(timeout=timeout))
            if frame.get("msg") == "ping":
                self._send(ws, {"msg": "pong", **({"id": frame["id"]} if frame.get("id") else {})})
                continue
            return frame

    def _wait_for(self, ws, predicate: Callable[[dict], bool]) -> dict:
        while True:
            frame = self._receive(ws)
            if predicate(frame):
                return frame

    def run_once(self) -> None:
        with connect(self.url, open_timeout=10, close_timeout=3) as ws:
            self._send(ws, {"msg": "connect", "version": "1", "support": ["1"]})
            self._wait_for(ws, lambda frame: frame.get("msg") == "connected")
            self._send(ws, {"msg": "method", "method": "login", "id": "login", "params": [{
                "user": {"username": self.username},
                "password": {"digest": self.password_digest, "algorithm": "sha-256"},
            }]})
            login = self._wait_for(ws, lambda frame: frame.get("msg") == "result" and frame.get("id") == "login")
            if login.get("error"):
                raise RuntimeError("Rocket.Chat realtime login failed")
            with self._room_lock:
                initial_rooms = sorted(self.room_ids)
            pending = {f"room-{index}" for index, _ in enumerate(initial_rooms)}
            for index, room_id in enumerate(initial_rooms):
                self._send(ws, {"msg": "sub", "id": f"room-{index}",
                                "name": "stream-room-messages", "params": [room_id, False]})
            while pending:
                frame = self._receive(ws)
                if frame.get("msg") == "ready":
                    pending.difference_update(frame.get("subs", []))
            self.connected.set()
            log.info("Realtime room stream ready: %s subscriptions", len(initial_rooms))
            sequence = len(initial_rooms)
            subscribed = set(initial_rooms)
            while not self._stopped.is_set():
                while True:
                    try:
                        room_id = self._new_rooms.get_nowait()
                    except queue.Empty:
                        break
                    if room_id in subscribed:
                        continue
                    self._send(ws, {"msg": "sub", "id": f"room-{sequence}",
                                    "name": "stream-room-messages", "params": [room_id, False]})
                    subscribed.add(room_id)
                    sequence += 1
                    log.info("Realtime room subscription added")
                try:
                    frame = self._receive(ws, timeout=1)
                except TimeoutError:
                    continue
                with self._room_lock:
                    room_ids = set(self.room_ids)
                message = room_message(frame, room_ids)
                if message:
                    self.on_message(message)

    def run_forever(self) -> None:
        while not self._stopped.is_set():
            try:
                self.run_once()
            except Exception as exc:  # reconnect without logging message bodies or credentials
                self.connected.clear()
                log.warning("realtime_stream_reconnect type=%s", type(exc).__name__)
                self._stopped.wait(self.reconnect_seconds)
