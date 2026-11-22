"""Local synthetic chat-only confirmation and read-only search integration check."""
import hashlib
import json
import re
import sys
import time
import uuid

import httpx
from setup import API, LOCAL


def main():
    creds = json.loads((LOCAL / "credentials.json").read_text(encoding="utf-8"))
    config = json.loads((LOCAL / "bot.json").read_text(encoding="utf-8"))
    rocket = API(**creds["employee"])
    room = config["room_id"]
    client = httpx.Client(base_url="http://127.0.0.1:8003", timeout=25, trust_env=False)
    response = client.post("/api/review/login", json=creds["employee"])
    response.raise_for_status()
    auth = response.json()
    client.headers.update({"X-Rocket-User": auth["user_id"], "X-Rocket-Token": auth["token"]})

    def send(text, parent=None):
        identity = "easytest" + uuid.uuid4().hex[:18]
        rocket.call("POST", "chat.sendMessage", {"message": {"_id": identity, "rid": room, "msg": text,
            **({"tmid": parent} if parent else {})}, "previewUrls": []})
        return identity

    def wait_reply(identity, timeout=260):
        reply_id = "draft" + hashlib.sha256(f"{room}:{identity}".encode()).hexdigest()[:24]
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                reply = rocket.call("GET", "chat.getMessage", params={"msgId": reply_id})["message"]
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code not in (400, 404):
                    raise
            except RuntimeError as exc:
                if "HTTP 400" not in str(exc) and "HTTP 404" not in str(exc):
                    raise
            else:
                if "잠시만 기다려" not in reply["msg"]:
                    return reply
            time.sleep(8)
        raise AssertionError("Timed out waiting for local bot reply")

    marker = "간편검증" + uuid.uuid4().hex[:6]
    if "--resume" in sys.argv:
        messages = rocket.call("GET", "groups.history", params={"roomId": room, "count": 30})["messages"]
        prior = next(m for m in messages if m["_id"].startswith("easytest") and m.get("u", {}).get("username") == creds["employee"]["username"] and m.get("msg", "").startswith("보고 간편검증"))
        source = prior["_id"]
        marker = re.search(r"간편검증[a-f0-9]{6}", prior["msg"]).group()
    else:
        source = send(f"보고 {marker} 검색 화면 수정 작업은 진행 중입니다. 진행률은 40%입니다.")
    print("Synthetic report sent; waiting for actual local Gemma.", flush=True)
    preview = wait_reply(source)
    assert "맞으면 `확정`" in preview["msg"], preview["msg"]
    assert not preview.get("tmid"), "Preview should be visible in the main test room"
    draft_id = hashlib.sha256(f"local-rocketchat:{room}:{source}".encode()).hexdigest()
    draft = client.get("/api/review/drafts/" + draft_id).json()
    assert draft["state"] == "DRAFT" and not draft["report_ids"]
    print("Gemma preview and no premature report storage: PASS", flush=True)
    # Target only this synthetic preview; never implicitly confirm an existing user draft.
    confirmation = wait_reply(send("확정", preview["_id"]))
    assert "보고 확정 완료" in confirmation["msg"], confirmation["msg"]
    saved = client.get("/api/review/drafts/" + draft_id).json()
    assert saved["state"] == "CONFIRMED" and saved["report_ids"]
    print("Chat-only author confirmation on preview thread: PASS", flush=True)
    answer = wait_reply(send("오늘 보고"))
    assert "내 확정 보고 조회" in answer["msg"] and source in answer["msg"]
    answer = wait_reply(send("조회 오늘 " + marker))
    assert "내 확정 보고 조회" in answer["msg"] and source in answer["msg"]
    incomplete = wait_reply(send("미완료 보고"))
    assert source in incomplete["msg"]
    repeated = wait_reply(send("확정", preview["_id"]))
    assert "이미 확정" in repeated["msg"]
    after = client.get("/api/review/drafts/" + draft_id).json()
    assert after["report_ids"] == saved["report_ids"] and after["version"] == saved["version"]
    result = client.get("/api/review/search", params={"q": "조회 오늘 " + marker})
    result.raise_for_status()
    assert result.json()["items"] and result.json()["llm_used"] is False
    other = client.post("/api/review/login", json=creds["admin"])
    other.raise_for_status()
    other = other.json()
    forbidden = client.get("/api/review/search", params={"q": "조회 오늘 " + marker},
        headers={"X-Rocket-User": other["user_id"], "X-Rocket-Token": other["token"]})
    forbidden.raise_for_status()
    assert forbidden.json()["items"] == []
    result = {"passed": True, "draft_id": draft_id, "report_ids": saved["report_ids"],
        "review_url": "http://127.0.0.1:8003/#" + draft_id,
        "checks": ["실제 Gemma", "방 안에 초안 표시", "채팅 확정", "본인 보고 조회", "날짜/검색어/미완료", "원문 링크", "중복 확정 방지", "타인 조회 차단"]}
    (LOCAL / "easy-smoke-results.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Search, original sources, unchanged confirmation version, duplicate and ownership guards: PASS", flush=True)
    print("Added synthetic report IDs: " + str(saved["report_ids"]), flush=True)


if __name__ == "__main__":
    main()
