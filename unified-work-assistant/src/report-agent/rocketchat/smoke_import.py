"""Synthetic local historical import: no old company data or final report writes."""
import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone

import httpx
from setup import API, LOCAL


def main():
    creds = json.loads((LOCAL / "credentials.json").read_text(encoding="utf-8"))
    config = json.loads((LOCAL / "bot.json").read_text(encoding="utf-8"))
    rocket = API(**creds["employee"])
    client = httpx.Client(base_url="http://127.0.0.1:8003", timeout=240, trust_env=False)
    response = client.post("/api/review/login", json=creds["employee"])
    response.raise_for_status()
    auth = response.json()
    client.headers.update({"X-Rocket-User": auth["user_id"], "X-Rocket-Token": auth["token"]})
    room = config["room_id"]
    ids = ["importtest"+uuid.uuid4().hex[:18] for _ in range(2)]
    raw = f"가져오기검증{ids[0][-6:]} 검색 화면 수정 작업은 진행 중입니다."
    for identity, text in zip(ids, [raw, "선택하지 않는 합성 대화입니다. 점심 메뉴를 확인합니다."]):
        rocket.call("POST", "chat.sendMessage", {"message": {"_id": identity, "rid": room, "msg": text}, "previewUrls": []})
    today = datetime.now(timezone(timedelta(hours=9))).date().isoformat()
    scope = {"room_id": room, "start": today, "end": today}
    response = client.post("/api/review/imports/preview", json=scope)
    response.raise_for_status()
    preview = response.json()
    assert not preview["persisted"] and not preview["llm_used"]
    rows = {row["message_id"]: row for row in preview["items"]}
    assert all(identity in rows for identity in ids)
    draft_ids = [hashlib.sha256(f"local-rocketchat:{room}:{identity}".encode()).hexdigest() for identity in ids]
    assert all(client.get("/api/review/drafts/"+identity).status_code == 404 for identity in draft_ids)
    print("Preview: original own messages visible; neither saved or sent to AI: PASS", flush=True)
    payload = {**scope, "as_of": preview["as_of"], "message_id": ids[0], "fingerprint": rows[ids[0]]["fingerprint"]}
    response = client.post("/api/review/imports/draft", json=payload)
    response.raise_for_status()
    result = response.json()
    draft = result["draft"]
    assert result["created"] and draft["state"] == "DRAFT" and not draft["report_ids"]
    assert draft["raw_message"] == raw and draft["submitted_at"] == rows[ids[0]]["submitted_at"]
    assert draft["revisions"][0]["action"] == "IMPORT"
    assert client.get("/api/review/drafts/"+draft_ids[1]).status_code == 404
    print("Actual Gemma: selected message only, draft state, original author/time/link and import audit: PASS", flush=True)
    repeat = client.post("/api/review/imports/draft", json=payload)
    repeat.raise_for_status()
    assert not repeat.json()["created"] and repeat.json()["draft"]["id"] == draft["id"]
    response = client.post("/api/review/imports/preview", json=scope)
    response.raise_for_status()
    assert next(r for r in response.json()["items"] if r["message_id"] == ids[0])["existing"] == "DRAFT"
    other = client.post("/api/review/login", json=creds["admin"])
    other.raise_for_status()
    other = other.json()
    denied = client.post("/api/review/imports/draft", json=payload, headers={"X-Rocket-User": other["user_id"], "X-Rocket-Token": other["token"]})
    assert denied.status_code == 404
    record = {"passed": True, "draft_id": draft["id"], "source_id": ids[0], "unselected_id": ids[1],
        "scope": scope, "payload": payload, "review_url": "http://127.0.0.1:8003/#"+draft["id"]}
    (LOCAL / "import-smoke-results.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Duplicate import / other-author rejection: PASS. One synthetic draft kept; no final report saved.", flush=True)


if __name__ == "__main__":
    main()
