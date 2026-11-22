"""End-to-end one-click report test; publishes one clearly marked synthetic report."""
import hashlib
import json
import re
import sys
import time
import uuid

import httpx

from setup import API, LOCAL


def main():
    cfg = json.loads((LOCAL / "bot.json").read_text(encoding="utf-8"))
    creds = json.loads((LOCAL / "credentials.json").read_text(encoding="utf-8"))
    employee = API(**creds["employee"])
    room = cfg["personal_rooms"][creds["employee"]["username"]]["room_id"]
    token = None
    action_text = ""
    source_id = ""
    verify_latest = "--verify-latest" in sys.argv
    if verify_latest:
        history = employee.call("GET", "groups.history", params={"roomId": room, "count": 30})
        action_text = next((row["msg"] for row in history["messages"]
                            if row.get("u", {}).get("username") == "report-bot"
                            and "quick-publish.html#" in row.get("msg", "")), "")
        match = re.search(r"quick-publish\.html#([^\s)]+)", action_text)
        token = match.group(1) if match else None
        draft_id = "latest-existing"
    else:
        source_id = "quicktest" + uuid.uuid4().hex[:18]
        draft_id = hashlib.sha256(f"local-rocketchat:{room}:{source_id}".encode()).hexdigest()
        raw = ("보고 [원클릭 게시 기능검증용 예시] 업무 비서 AI Agent의 개인방 보고 미리보기 버튼 구현을 완료했습니다. "
               "업무 비서 AI Agent의 중복 클릭 방지 테스트는 진행 중이며 진행률은 80%입니다. "
               "업무 비서 AI Agent의 팀 보고방 게시 결과 확인은 다음에 진행할 예정입니다.")
        employee.call("POST", "chat.sendMessage", {
            "message": {"_id": source_id, "rid": room, "msg": raw}, "previewUrls": [],
        })
        action_id = "action" + hashlib.sha256(f"{room}:{source_id}".encode()).hexdigest()[:24]
        for _ in range(60):
            response = employee.client.get("/api/v1/chat.getMessage", params={"msgId": action_id})
            if response.status_code == 200 and response.json().get("message"):
                action_text = response.json()["message"]["msg"]
                match = re.search(r"quick-publish\.html#([^\s)]+)", action_text)
                if match:
                    token = match.group(1)
                    break
            time.sleep(2)
    if not token:
        raise RuntimeError("One-click link did not appear; source message remains available for diagnosis.")
    assert "✅ 이대로 보고" in action_text and "8자리" not in action_text

    with httpx.Client(base_url="http://127.0.0.1:8003", timeout=45, trust_env=False) as review:
        linked = review.post("/api/review/link-login", json={"token": token})
        linked.raise_for_status()
        identity = linked.json()
        assert identity["token"].startswith("app:")
        context = review.get("/api/review/context", headers={
            "X-Rocket-User": identity["user_id"], "X-Rocket-Token": identity["token"],
        })
        context.raise_for_status()
        assert context.json()["room"].startswith("개인보고-")
        first = review.post("/api/review/quick-publish", json={"token": token})
        first.raise_for_status()
        first_result = first.json()
        second = review.post("/api/review/quick-publish", json={"token": token})
        second.raise_for_status()
        second_result = second.json()
    assert first_result["state"] == "SENT"
    assert first_result["already_sent"] is verify_latest
    assert second_result["state"] == "SENT" and second_result["already_sent"]
    assert first_result["url"] == second_result["url"]
    message_id = re.search(r"[?&]msg=([^&]+)", first_result["url"]).group(1)
    posted = employee.call("GET", "chat.getMessage", params={"msgId": message_id})["message"]
    assert posted["rid"] == cfg["channels"]["reports"]["room_id"]
    assert "미리보기 버튼 구현" in posted["msg"] and "중복 클릭 방지 테스트" in posted["msg"]
    result = {
        "verified": True,
        "draft_id": draft_id,
        "source_message_id": source_id,
        "publication_message_id": message_id,
        "publication_url": first_result["url"],
        "passwordless_review": True,
        "duplicate_click_prevented": second_result["already_sent"],
    }
    (LOCAL / "quick-publish-smoke-results.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
