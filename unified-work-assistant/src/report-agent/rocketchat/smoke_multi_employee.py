"""Local E2E: provisioned employees have isolated rooms and separate confirmed reports."""
import hashlib
import json
import sqlite3
import time
import uuid
from pathlib import Path

import httpx

from setup import API, LOCAL, employee_accounts


def wait_for_draft(draft_id: str):
    database = Path(__file__).resolve().parent.parent / "backend" / "work_assistant.db"
    for _ in range(60):
        with sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True) as db:
            row = db.execute(
                "SELECT author_username, room_id, state FROM chat_drafts WHERE id=?", (draft_id,),
            ).fetchone()
        if row:
            return row
        time.sleep(2)
    raise RuntimeError("The additional employee draft was not processed in time")


def main():
    credentials = json.loads((LOCAL / "credentials.json").read_text(encoding="utf-8"))
    config = json.loads((LOCAL / "bot.json").read_text(encoding="utf-8"))
    employees = [account for _, account, _ in employee_accounts(credentials)]
    assert len(employees) >= 4, "Expected at least four PoC employees"
    assert set(config["personal_rooms"]) == {account["username"] for account in employees}

    bot_name = credentials["bot"]["username"]
    bot = API(**credentials["bot"])
    for account in employees:
        username = account["username"]
        room = config["personal_rooms"][username]
        members = bot.call(
            "GET", "groups.members", params={"roomId": room["room_id"], "count": 3},
        )
        assert members["total"] == 2
        assert {member["username"] for member in members["members"]} == {username, bot_name}

    author = employees[1]
    outsider = employees[2]
    author_api = API(**author)
    outsider_api = API(**outsider)
    admin_api = API(**credentials["admin"])
    room = config["personal_rooms"][author["username"]]
    denied = outsider_api.client.get(
        "/api/v1/groups.info", params={"roomId": room["room_id"]},
    )
    assert denied.status_code in (400, 401, 403, 404), denied.status_code

    message_id = "multistaff" + uuid.uuid4().hex[:16]
    raw = ("보고 AI 업무 비서 프로젝트의 테스트 직원 네 명 등록을 완료했습니다. "
           "직원별 개인 보고방 분리 검증은 진행 중이며 진행률은 80%입니다.")
    author_api.call("POST", "chat.sendMessage", {
        "message": {"_id": message_id, "rid": room["room_id"], "msg": raw}, "previewUrls": [],
    })
    draft_id = hashlib.sha256(
        f"local-rocketchat:{room['room_id']}:{message_id}".encode(),
    ).hexdigest()
    row = wait_for_draft(draft_id)
    assert row == (author["username"], room["room_id"], "DRAFT")

    with httpx.Client(base_url="http://127.0.0.1:8003", timeout=30, trust_env=False) as review:
        author_headers = {
            "X-Rocket-User": author_api.user_id,
            "X-Rocket-Token": author_api.client.headers["X-Auth-Token"],
        }
        draft = review.get(f"/api/review/drafts/{draft_id}", headers=author_headers)
        draft.raise_for_status()
        payload = draft.json()
        for item in payload["items"]:
            item["project"] = "ai-assistant"
            item["task"] = "[다중 직원 테스트] " + item["task"].removeprefix("[다중 직원 기능검증] ")
        confirmed = review.post(
            f"/api/review/drafts/{draft_id}/confirm", headers=author_headers,
            json={"version": payload["version"], "items": payload["items"],
                  "reason": "추가 직원 계정·개인방·저장 분리 기능검증"},
        )
        confirmed.raise_for_status()
        assert confirmed.json()["state"] == "CONFIRMED"

        outsider_read = review.get(f"/api/review/drafts/{draft_id}", headers={
            "X-Rocket-User": outsider_api.user_id,
            "X-Rocket-Token": outsider_api.client.headers["X-Auth-Token"],
        })
        assert outsider_read.status_code == 404

        dashboard = review.get("/api/review/manager/dashboard", headers={
            "X-Rocket-User": admin_api.user_id,
            "X-Rocket-Token": admin_api.client.headers["X-Auth-Token"],
        })
        dashboard.raise_for_status()
        names = {employee["username"] for employee in dashboard.json()["employees"]}
        assert author["username"] in names

    print(json.dumps({
        "employee_count": len(employees), "personal_room_count": len(config["personal_rooms"]),
        "tested_employee": author["username"], "cross_room_access": "denied",
        "cross_report_access": "denied", "manager_dashboard": "visible", "published": False,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
