"""Synthetic local test: draft -> edit -> confirm -> revise -> dashboard; no real channel."""
import hashlib
import json
import time
import uuid

import httpx
from setup import API, LOCAL


def main():
    creds = json.loads((LOCAL / "credentials.json").read_text(encoding="utf-8"))
    config = json.loads((LOCAL / "bot.json").read_text(encoding="utf-8"))
    rocket = API(**creds["employee"])
    review = httpx.Client(base_url="http://127.0.0.1:8003", timeout=20, trust_env=False)
    response = review.post("/api/review/login", json=creds["employee"])
    response.raise_for_status()
    auth = response.json()
    review.headers.update({"X-Rocket-User": auth["user_id"], "X-Rocket-Token": auth["token"]})
    legacy = httpx.Client(base_url="http://127.0.0.1:8002", timeout=20, trust_env=False)
    before_count = legacy.get("/api/reports").json()["total"]
    source_id = "reviewtest" + uuid.uuid4().hex[:18]
    raw = f"업무비서 기술 자료조사({source_id})는 완료했습니다. 공간정보 검색 화면은 수정 중입니다."
    draft_id = hashlib.sha256(f"local-rocketchat:{config['room_id']}:{source_id}".encode()).hexdigest()
    rocket.call("POST", "chat.sendMessage", {"message": {"_id": source_id, "rid": config["room_id"], "msg": "!보고 " + raw}, "previewUrls": []})
    print("Submitted synthetic review workflow report.", flush=True)
    deadline = time.monotonic() + 260
    while time.monotonic() < deadline:
        response = review.get(f"/api/review/drafts/{draft_id}")
        if response.status_code == 200:
            break
        time.sleep(10)
    response.raise_for_status()
    draft = response.json()
    assert draft["raw_message"] == raw
    assert draft["state"] == "DRAFT" and not draft["report_ids"]
    assert legacy.get("/api/reports").json()["total"] == before_count
    assert len(draft["items"]) >= 2
    items = draft["items"]
    for item in items:
        item["status"] = "IN_PROGRESS"
        item["progress"] = None
    items[0]["task"] = "직원 수정 · 업무비서 기술 자료조사"
    items[0]["status"] = "DONE"
    items[1]["progress"] = 35
    payload = {"version": draft["version"], "items": items, "reason": "합성 테스트: 직원이 초안을 수정"}
    response = review.put(f"/api/review/drafts/{draft_id}", json=payload)
    response.raise_for_status()
    edited = response.json()
    assert edited["version"] == draft["version"] + 1 and not edited["report_ids"]
    assert legacy.get("/api/reports").json()["total"] == before_count
    print("Draft editing and no premature report storage: PASS", flush=True)
    payload["version"] = edited["version"]
    payload["reason"] = "합성 테스트: 보고 확정"
    response = review.post(f"/api/review/drafts/{draft_id}/confirm", json=payload)
    response.raise_for_status()
    confirmed = response.json()
    ids = confirmed["report_ids"]
    assert len(ids) == len(items)
    assert legacy.get("/api/reports").json()["total"] == before_count + len(items)
    repeated = review.post(f"/api/review/drafts/{draft_id}/confirm", json=payload)
    repeated.raise_for_status()
    assert repeated.json()["report_ids"] == ids
    assert repeated.json()["version"] == confirmed["version"]
    print("Confirmation, separate task records and duplicate prevention: PASS", flush=True)
    first = legacy.get(f"/api/reports/{ids[0]}").json()
    assert first["progress"] is None and draft_id in first["review_url"]
    assert source_id in first["source_url"]
    blocked = legacy.put(f"/api/reports/{ids[0]}", json={"task": "우회 수정", "status": "DONE", "progress": 100})
    assert blocked.status_code == 409
    # Verify another allowed user's token cannot open this author's draft.
    other = review.post("/api/review/login", json=creds["admin"])
    other.raise_for_status()
    other_auth = other.json()
    forbidden = review.get(f"/api/review/drafts/{draft_id}", headers={"X-Rocket-User": other_auth["user_id"], "X-Rocket-Token": other_auth["token"]})
    assert forbidden.status_code == 404
    print("Source links and author ownership / legacy edit guard: PASS", flush=True)
    time.sleep(10)
    payload["version"] = confirmed["version"]
    payload["items"][1]["progress"] = None
    payload["items"][1]["next_action"] = "다음 보고에서 진행률 확인"
    payload["reason"] = "합성 테스트: 불명확한 진행률을 비우고 이력 보존"
    response = review.post(f"/api/review/drafts/{draft_id}/confirm", json=payload)
    response.raise_for_status()
    revised = response.json()
    assert revised["report_ids"] == ids and len(revised["revisions"]) == 3
    dashboard_response = legacy.get("/api/dashboard")
    dashboard_response.raise_for_status()
    employee = next(x for x in dashboard_response.json()["employees"] if x["name"] == "RC 테스트 · poc-employee")
    assert employee["progress"] is None and employee["reported"]
    stale = review.post(f"/api/review/drafts/{draft_id}/confirm", json={**payload, "reason": "stale", "items": items[:1]})
    assert stale.status_code == 409
    result = {"passed": True, "draft_id": draft_id, "report_ids": ids, "review_url": f"http://127.0.0.1:8003/#{draft_id}",
              "checks": ["실제 Gemma 초안", "직원 수정", "확정 전 보고 미저장", "확정 후 DB/대시보드", "다중 업무 분리", "중복 방지", "작성자 권한", "원문 출처", "수정 이력", "진행률 null 유지", "오래된 버전 수정 차단"]}
    (LOCAL / "review-smoke-results.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Revision history, null progress and dashboard: PASS", flush=True)
    print(result["review_url"], flush=True)


if __name__ == "__main__":
    main()
