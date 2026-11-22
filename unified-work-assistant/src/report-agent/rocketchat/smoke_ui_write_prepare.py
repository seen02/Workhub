"""Create one labelled private draft and capture its passwordless edit link; never publish."""
import hashlib
import json
import re
import sqlite3
import time
import uuid
from pathlib import Path

from setup import API, LOCAL


def main():
    cfg = json.loads((LOCAL / "bot.json").read_text(encoding="utf-8"))
    creds = json.loads((LOCAL / "credentials.json").read_text(encoding="utf-8"))
    api = API(**creds["employee"])
    room = cfg["personal_rooms"][creds["employee"]["username"]]["room_id"]
    source = "uiwritetest" + uuid.uuid4().hex[:18]
    draft_id = hashlib.sha256(f"local-rocketchat:{room}:{source}".encode()).hexdigest()
    raw = "보고 [UI 저장 기능검증용 가상 보고입니다] 업무 비서 AI Agent 수정 화면 점검은 진행 중이며 진행률은 10%입니다."
    api.call("POST", "chat.sendMessage", {"message": {"_id": source, "rid": room, "msg": raw}, "previewUrls": []})
    database = Path(__file__).resolve().parent.parent / "backend" / "work_assistant.db"
    for _ in range(90):
        with sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True) as db:
            row = db.execute("SELECT state,current_data FROM chat_drafts WHERE id=?", (draft_id,)).fetchone()
            shown = db.execute("SELECT 1 FROM chat_draft_revisions WHERE draft_id=? AND action='CHAT_PREVIEW'", (draft_id,)).fetchone()
        if row and shown:
            break
        time.sleep(2)
    else:
        raise RuntimeError("Draft preview timeout; source retained and no automatic resend.")
    action_id = "action" + hashlib.sha256(f"{room}:{source}".encode()).hexdigest()[:24]
    action = api.call("GET", "chat.getMessage", params={"msgId": action_id})["message"]["msg"]
    match = re.search(r"\[보고 내용 수정하기\]\((http://127\.0\.0\.1:8003/\?access=[A-Za-z0-9_.-]+#[a-f0-9]{64})\)", action)
    assert match and match.group(1).endswith("#" + draft_id), action
    result = {"draft_id": draft_id, "source_id": source, "link": match.group(1),
              "initial_items": json.loads(row[1]), "published": False}
    (LOCAL / "ui-write-smoke.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"draft_id": draft_id, "passwordless_link": True, "published": False}, ensure_ascii=False))


if __name__ == "__main__":
    main()
