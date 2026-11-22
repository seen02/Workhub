"""Local E2E: four employees submit different reports and verify isolated results."""
import argparse
import hashlib
import json
import sqlite3
import time
import uuid
from pathlib import Path

import httpx

from setup import API, LOCAL, employee_accounts


DATABASE = Path(__file__).resolve().parent.parent / "backend" / "work_assistant.db"
CASES = (
    ("ai-assistant", "보고 AI업무비서 개발 프로젝트의 관리자 보고 검색 형식 검증을 완료했습니다."),
    ("spatial-agent", "보고 공간정보 Agent 프로젝트의 좌표 검색 정확도 검증을 진행 중이며 진행률은 55%입니다."),
    ("ai-assistant", "보고 AI업무비서 개발 프로젝트의 직원별 개인방 권한 검증을 진행 중이며 진행률은 65%입니다."),
    ("spatial-agent", "보고 공간정보 Agent 프로젝트의 검색 결과 지도 표시 검증을 완료했습니다."),
)


def db_rows(sql, params=()):
    with sqlite3.connect(f"file:{DATABASE.as_posix()}?mode=ro", uri=True) as db:
        return db.execute(sql, params).fetchall()


def wait_until(check, message, timeout=600):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = check()
        if result:
            return result
        time.sleep(3)
    raise RuntimeError(message)


def auth_headers(api):
    return {"X-Rocket-User": api.user_id, "X-Rocket-Token": api.client.headers["X-Auth-Token"]}


def main(existing_run=None):
    credentials = json.loads((LOCAL / "credentials.json").read_text(encoding="utf-8"))
    config = json.loads((LOCAL / "bot.json").read_text(encoding="utf-8"))
    employees = [account for _, account, _ in employee_accounts(credentials)]
    assert len(employees) == len(CASES) == 4
    clients = [API(**account) for account in employees]
    run_id = existing_run or uuid.uuid4().hex[:10]
    drafts = []

    if existing_run:
        existing = db_rows(
            "SELECT author_username,room_id,id FROM chat_drafts WHERE message_id LIKE ?",
            (f"staffreport{run_id}%",),
        )
        by_author = {author: (room_id, draft_id) for author, room_id, draft_id in existing}
        assert set(by_author) == {account["username"] for account in employees}
        for account, api in zip(employees, clients):
            room_id, draft_id = by_author[account["username"]]
            drafts.append((account, api, room_id, draft_id))
    else:
        for index, (account, api, (_, raw)) in enumerate(zip(employees, clients, CASES), 1):
            room_id = config["personal_rooms"][account["username"]]["room_id"]
            message_id = f"staffreport{run_id}{index}"
            api.call("POST", "chat.sendMessage", {
                "message": {"_id": message_id, "rid": room_id, "msg": raw}, "previewUrls": [],
            })
            draft_id = hashlib.sha256(f"local-rocketchat:{room_id}:{message_id}".encode()).hexdigest()
            drafts.append((account, api, room_id, draft_id))

    ids = [draft_id for _, _, _, draft_id in drafts]
    placeholders = ",".join("?" for _ in ids)

    def previews_ready():
        rows = db_rows(
            f"SELECT draft_id FROM chat_draft_revisions WHERE action='CHAT_PREVIEW' AND draft_id IN ({placeholders})",
            ids,
        )
        return len({row[0] for row in rows}) == 4

    wait_until(previews_ready, "Four employee previews were not generated")

    if not existing_run:
        for account, api, room_id, draft_id in drafts:
            api.call("POST", "chat.sendMessage", {
                "message": {"_id": f"staffpublish{run_id}{draft_id[:6]}", "rid": room_id,
                            "msg": f"보고 {draft_id[:8]}"},
                "previewUrls": [],
            })

    def publications_ready():
        rows = db_rows(
            f"SELECT draft_id,state FROM chat_publications WHERE draft_id IN ({placeholders})", ids,
        )
        return len(rows) == 4 and all(state == "SENT" for _, state in rows)

    wait_until(publications_ready, "Four employee reports were not published")

    verified = []
    with httpx.Client(base_url="http://127.0.0.1:8003", timeout=30, trust_env=False) as review:
        for account, api, _, draft_id in drafts:
            response = review.get("/api/review/search", params={"q": "오늘 보고"}, headers=auth_headers(api))
            response.raise_for_status()
            own = [item for item in response.json()["items"] if item["author"] == account["username"]]
            assert own and all(item["author"] == account["username"] for item in response.json()["items"])
            verified.append({
                "employee": account["username"], "task": own[0]["task"],
                "project": own[0]["project"], "state": "CONFIRMED_AND_PUBLISHED",
            })

        for index, (account, api, _, _) in enumerate(drafts):
            other_draft = drafts[(index + 1) % len(drafts)][3]
            denied = review.get(f"/api/review/drafts/{other_draft}", headers=auth_headers(api))
            assert denied.status_code == 404

        admin = API(**credentials["admin"])
        dashboard = review.get("/api/review/manager/dashboard", headers=auth_headers(admin))
        dashboard.raise_for_status()
        dashboard_names = {row["username"] for row in dashboard.json()["employees"]}
        assert {account["username"] for account in employees}.issubset(dashboard_names)

    print(json.dumps({
        "run": run_id, "reports": verified, "personal_search": "isolated",
        "cross_report_access": "denied", "manager_employee_count": len(dashboard_names),
        "team_publications": 4,
    }, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify-run")
    main(parser.parse_args().verify_run)
