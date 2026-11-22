"""Local synthetic E2E: one private draft, one explicitly published test report."""
import argparse
import hashlib
import json
import sqlite3
import time
import uuid
from pathlib import Path
import httpx
from setup import API, LOCAL


def main(phase):
    cfg = json.loads((LOCAL / "bot.json").read_text(encoding="utf-8"))
    creds = json.loads((LOCAL / "credentials.json").read_text(encoding="utf-8"))
    employee = API(**creds["employee"])
    review = httpx.Client(base_url="http://127.0.0.1:8003", timeout=30, trust_env=False)
    login = review.post("/api/review/login", json=creds["employee"])
    login.raise_for_status()
    session = login.json()
    review.headers.update({"X-Rocket-User": session["user_id"], "X-Rocket-Token": session["token"]})
    def req(method, path, body=None):
        for attempt in range(5):
            response = review.request(method, "/api/review"+path, json=body)
            if response.status_code != 429:
                break
            print("Rate limited; retrying the same idempotent request", flush=True)
            time.sleep(15)
        if not response.is_success:
            raise RuntimeError(f"{path}: {response.status_code}: {response.json().get('detail')}")
        return response.json()
    def count_reports():
        path = Path(__file__).resolve().parent.parent / "backend" / "work_assistant.db"
        with sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True) as db:
            return db.execute("SELECT count(*) FROM reports").fetchone()[0]
    state_path = LOCAL / "team-smoke-results.json"
    if phase == "draft":
        assert req("GET", "/context")["private_mode"]
        mid = "teamtest" + uuid.uuid4().hex[:18]
        room = cfg["personal_rooms"][creds["employee"]["username"]]["room_id"]
        raw = "보고 기능검증용 AI업무비서 화면 검토는 완료했습니다. 공간정보 Agent 검색 테스트는 40% 진행 중입니다."
        employee.call("POST", "chat.sendMessage", {"message": {"_id": mid, "rid": room, "msg": raw}})
        draft_id = hashlib.sha256(f"local-rocketchat:{room}:{mid}".encode()).hexdigest()
        result = {"draft_id": draft_id, "message_id": mid, "core_reports_before": count_reports()}
        state_path.write_text(json.dumps(result), encoding="utf-8")
        for attempt in range(12):
            response = review.get("/api/review/drafts/"+draft_id)
            if response.status_code == 200:
                d = response.json()
                assert d["state"] == "DRAFT" and not d["publications"] and not d["report_ids"]
                print("PASS: actual Gemma private draft, no final report/publication")
                return
            time.sleep(8)
        raise RuntimeError("Draft not ready; inspect worker log")
    result = json.loads(state_path.read_text(encoding="utf-8"))
    d = req("GET", "/drafts/"+result["draft_id"])
    items = d["items"]
    for item in items:
        item["project"] = "spatial-agent" if "공간" in item["task"] or "검색" in item["task"] else "ai-assistant"
    d = req("POST", "/drafts/"+d["id"]+"/confirm", {"version": d["version"], "items": items, "reason": "기능검증용 합성 보고 확인"})
    assert d["state"] == "CONFIRMED" and all(p["state"] == "PENDING" for p in d["publications"]) and not d["report_ids"]
    assert count_reports() == result["core_reports_before"]
    view = req("GET", "/drafts/"+d["id"]+"/publication-preview")
    assert "8003" not in view["text"] and "개인보고" not in view["text"]
    body = {"version": view["version"], "preview_hash": view["preview_hash"]}
    sent = req("POST", "/drafts/"+d["id"]+"/publish", body)
    again = req("POST", "/drafts/"+d["id"]+"/publish", body)
    assert sent["state"] == "SENT" and again["already_sent"]
    message_id = sent["url"].split("?msg=")[1]
    posted = employee.call("GET", "chat.getMessage", params={"msgId": message_id})["message"]
    assert posted["rid"] == cfg["channels"]["reports"]["room_id"] and posted["msg"] == view["text"]
    assert count_reports() == result["core_reports_before"]
    denied = review.get("/api/review/drafts/"+d["id"], headers={"X-Review-Room": "legacy"})
    assert denied.status_code == 404
    result.update(publication=sent, verified=True)
    state_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print("PASS: personal save remains private; explicit publication; duplicate safe; wrong room rejected; legacy report count preserved")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("phase", choices=["draft", "publish"])
    main(p.parse_args().phase)
