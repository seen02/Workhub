import json

from app.rocketchat.realtime import RoomMessageStream, normalize_message, room_message


def test_room_message_accepts_only_allowlisted_room_events():
    message = {"_id": "m1", "rid": "room-1", "msg": "보고 테스트", "u": {"username": "employee"}}
    frame = {"msg": "changed", "collection": "stream-room-messages",
             "fields": {"eventName": "room-1", "args": [message]}}
    assert room_message(frame, {"room-1"}) == message
    assert room_message(frame, {"other"}) is None
    assert room_message({**frame, "collection": "users"}, {"room-1"}) is None


def test_normalize_message_converts_meteor_ejson_timestamp():
    message = {"_id": "m1", "ts": {"$date": 1789000000000}}
    normalized = normalize_message(message)
    assert normalized["ts"] == "2026-09-10T00:26:40Z"
    assert message["ts"] == {"$date": 1789000000000}


def test_stream_replies_to_ping_before_returning_data():
    class FakeWebSocket:
        def __init__(self):
            self.frames = iter([json.dumps({"msg": "ping", "id": "p1"}),
                                json.dumps({"msg": "connected"})])
            self.sent = []

        def recv(self, timeout):
            return next(self.frames)

        def send(self, value):
            self.sent.append(json.loads(value))

    stream = RoomMessageStream("http://127.0.0.1:3000", "bot", "secret", ["room-1"], lambda _: None)
    ws = FakeWebSocket()
    assert stream._receive(ws) == {"msg": "connected"}
    assert ws.sent == [{"msg": "pong", "id": "p1"}]


def test_new_room_is_added_only_once():
    stream = RoomMessageStream("http://127.0.0.1:3000", "bot", "secret", ["room-1"], lambda _: None)
    assert stream.add_room("room-2")
    assert not stream.add_room("room-2")
    assert stream._new_rooms.get_nowait() == "room-2"
