"""Synthetic agent-development report: private save + preview, NEVER publish."""
import hashlib
import json
import time
import uuid

import httpx
from setup import API, LOCAL


def main():
    cfg = json.loads((LOCAL / "bot.json").read_text(encoding="utf-8"))
    creds = json.loads((LOCAL / "credentials.json").read_text(encoding="utf-8"))
    employee = API(**creds["employee"])
    room = cfg["personal_rooms"][creds["employee"]["username"]]["room_id"]
    mid = "agenttest" + uuid.uuid4().hex[:18]
    draft_id = hashlib.sha256(f"local-rocketchat:{room}:{mid}".encode()).hexdigest()
    raw = ("보고 [기능검증용 예시이며 진행률은 테스트 수치입니다] "
           "업무 비서 AI Agent의 프로젝트별 보고 양식 수정은 완료했습니다. "
           "개인 보고 수정·저장 화면의 사용성 테스트는 진행 중이며 진행률은 70%입니다. "
           "로켓챗 요청 제한 발생 시 대기시간 안내와 안전한 재시도 처리 개발은 아직 시작하지 않았고 다음에 진행할 예정입니다.")
    employee.call("POST", "chat.sendMessage", {"message": {"_id": mid, "rid": room, "msg": raw}, "previewUrls": []})
    result = {"draft_id": draft_id, "message_id": mid, "review_url": f"http://127.0.0.1:8003/#{draft_id}", "published": False}
    output = LOCAL / "agent-report-smoke-results.json"
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    with httpx.Client(base_url="http://127.0.0.1:8003", timeout=30, trust_env=False) as review:
        login = review.post("/api/review/login", json=creds["employee"])
        login.raise_for_status()
        auth = login.json()
        review.headers.update({"X-Rocket-User": auth["user_id"], "X-Rocket-Token": auth["token"]})
        # Poll through the review API so the test works with PostgreSQL and never reads DB files directly.
        for attempt in range(45):
            detail = review.get("/api/review/drafts/" + draft_id)
            if detail.status_code == 200:
                draft = detail.json()
                break
            if detail.status_code != 404:
                detail.raise_for_status()
            time.sleep(2)
        else:
            raise RuntimeError("Draft is not ready. Message ID saved; do not resend automatically.")
        version = draft["version"]
        model = draft["model"]
        items = draft["items"]
        statuses = {item["status"] for item in items}
        assert {"DONE", "IN_PROGRESS", "NOT_STARTED"}.issubset(statuses), items
        assert any(item["status"] == "IN_PROGRESS" and item["progress"] == 70 for item in items), items
        assert all(item["progress"] != 70 for item in items if item["status"] != "IN_PROGRESS"), items
        assert model.startswith("gemma"), model
        for item in items:
            item["project"] = "ai-assistant"
            # Make the synthetic nature visible in any future manually published version.
            item["task"] = "[테스트 예시] " + item["task"]
        def request(method, endpoint, body=None):
            for retry in range(3):
                response = review.request(method, "/api/review/drafts/"+draft_id+endpoint, json=body)
                if response.status_code != 429:
                    break
                time.sleep(15)
            if not response.is_success:
                raise RuntimeError(f"Review HTTP {response.status_code}: {response.json().get('detail')}")
            return response.json()
        saved = request("POST", "/confirm", {"version": version, "items": items, "reason": "새 Agent 개발 예시의 양식 검증 · 팀 게시 안 함"})
        assert saved["state"] == "CONFIRMED" and not saved["publications"] and not saved["report_ids"]
        preview = request("GET", "/publication-preview")
        assert preview["text"].startswith("**[업무목록]**") and "70%" in preview["text"]
        assert "(✅ 완료)" in preview["text"] and "(⏳ 예정)" in preview["text"]
        assert preview["publication"] is None
    result.update(model=model, items=items, preview=preview["text"], verified=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
