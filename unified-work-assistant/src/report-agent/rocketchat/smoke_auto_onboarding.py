"""Verify automatic new-employee onboarding against the local Rocket.Chat.

The script creates a disposable account, adds it to the shared report room,
waits for report-bot to create and subscribe to its personal room, verifies a
help response, and removes only the resources created by this run.
"""
from __future__ import annotations

import hashlib
import json
import secrets
import time
import uuid

from setup import API, LOCAL


def wait_for_personal_room(employee: API, room_name: str, timeout: float = 75.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = employee.call("GET", "groups.list", params={"count": 100})
        room = next((item for item in result.get("groups", [])
                     if item.get("name") == room_name), None)
        if room:
            return room
        time.sleep(2)
    raise RuntimeError("report-bot did not create the personal room within 75 seconds")


def wait_for_help(employee: API, room_id: str, source_id: str, timeout: float = 30.0) -> None:
    reply_id = "draft" + hashlib.sha256(f"{room_id}:{source_id}".encode()).hexdigest()[:24]
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = employee.client.get("/api/v1/chat.getMessage", params={"msgId": reply_id})
        if response.status_code == 200:
            message = response.json().get("message", {})
            if "개인보고 방 사용법" in message.get("msg", ""):
                return
        time.sleep(1)
    raise RuntimeError("new personal room was not subscribed or did not answer help")


def main() -> None:
    config = json.loads((LOCAL / "bot.json").read_text(encoding="utf-8"))
    credentials = json.loads((LOCAL / "credentials.json").read_text(encoding="utf-8"))
    admin = API(**credentials["admin"])
    bot = API(**credentials["bot"])
    reports_room_id = config["channels"]["reports"]["room_id"]
    suffix = uuid.uuid4().hex[:8]
    username = f"poc-auto-{suffix}"
    password = secrets.token_urlsafe(24)
    user_id = None
    personal_room_id = None
    cleanup = []
    verified = False
    try:
        created = admin.call("POST", "users.create", {
            "username": username,
            "password": password,
            "name": "자동 등록 기능검증 직원",
            "email": f"{username}@example.invalid",
            "roles": ["user"],
            "verified": True,
            "joinDefaultChannels": False,
            "sendWelcomeEmail": False,
            "requirePasswordChange": False,
        })["user"]
        user_id = created["_id"]
        admin.call("POST", "groups.invite", {
            "roomId": reports_room_id, "userId": user_id,
        })
        employee = API(username, password)
        room = wait_for_personal_room(employee, f"개인보고-{username}")
        personal_room_id = room["_id"]
        members = employee.call("GET", "groups.members", params={
            "roomId": personal_room_id, "count": 3,
        })
        member_names = {member["username"] for member in members.get("members", [])}
        if members.get("total") != 2 or member_names != {username, credentials["bot"]["username"]}:
            raise RuntimeError("automatically created room has unexpected members")
        source_id = "onboard" + suffix
        employee.call("POST", "chat.sendMessage", {
            "message": {"_id": source_id, "rid": personal_room_id, "msg": "도움말"},
            "previewUrls": [],
        })
        wait_for_help(employee, personal_room_id, source_id)
        verified = True
    finally:
        if user_id:
            try:
                admin.call("POST", "groups.kick", {
                    "roomId": reports_room_id, "userId": user_id,
                })
                cleanup.append("report-membership")
            except RuntimeError:
                pass
        if personal_room_id:
            try:
                bot.call("POST", "groups.delete", {"roomId": personal_room_id})
                cleanup.append("personal-room")
            except RuntimeError:
                pass
        if user_id:
            try:
                admin.call("POST", "users.delete", {"userId": user_id})
                cleanup.append("test-user")
            except RuntimeError:
                pass
    result = {
        "verified": verified,
        "automatic_room_created": verified,
        "exact_two_member_boundary": verified,
        "realtime_help_response": verified,
        "cleanup": cleanup,
    }
    (LOCAL / "auto-onboarding-smoke-results.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not verified:
        raise RuntimeError("automatic onboarding smoke test failed")


if __name__ == "__main__":
    main()
