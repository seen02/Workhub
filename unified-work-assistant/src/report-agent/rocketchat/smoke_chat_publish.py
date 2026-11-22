"""One explicitly labelled synthetic local report; --publish posts to the local team room."""
import argparse
import hashlib
import json
import sqlite3
import time
import uuid
from pathlib import Path

from setup import API, LOCAL


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--publish", action="store_true")
    parser.add_argument("--resume", action="store_true", help="Continue the saved synthetic draft without creating another")
    args = parser.parse_args()
    cfg = json.loads((LOCAL / "bot.json").read_text(encoding="utf-8"))
    creds = json.loads((LOCAL / "credentials.json").read_text(encoding="utf-8"))
    api = API(**creds["employee"])
    room = cfg["personal_rooms"][creds["employee"]["username"]]["room_id"]
    database = Path(__file__).resolve().parent.parent / "backend" / "work_assistant.db"
    def query(sql, values=()):
        with sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True) as db:
            return db.execute(sql, values).fetchall()
    before = query("SELECT COUNT(*) FROM reports")[0][0]
    source = "directtest" + uuid.uuid4().hex[:18]
    draft_id = hashlib.sha256(f"local-rocketchat:{room}:{source}".encode()).hexdigest()
    raw = ("보고 [기능 검증용 가상 보고입니다. 실제 업무 실적이 아닙니다.] "
           "업무 비서 AI Agent 테스트용 개인방 미리보기 점검은 완료했습니다. "
           "업무 비서 AI Agent 테스트용 보고 명령 점검은 진행 중이며 진행률은 45%입니다. "
           "업무 비서 AI Agent 테스트용 수정 화면 점검은 내일 할 예정이며 아직 시작하지 않았습니다.")
    output = {"draft_id": draft_id, "source_id": source, "published": False}
    output_file = LOCAL / "chat-direct-smoke-results.json"
    if args.resume:
        output = json.loads(output_file.read_text(encoding="utf-8"))
        draft_id, source = output["draft_id"], output["source_id"]
        if output.get("command_id"):
            raise RuntimeError("A publication command was already sent; inspect it instead of sending again.")
    else:
        api.call("POST", "chat.sendMessage", {"message": {"_id": source, "rid": room, "msg": raw}, "previewUrls": []})
    output_file.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Synthetic draft sent; waiting for actual Gemma preview.", flush=True)
    for _ in range(90):
        rows = query("SELECT d.current_data,d.model FROM chat_drafts d JOIN chat_draft_revisions r ON r.draft_id=d.id WHERE d.id=? AND r.action='CHAT_PREVIEW'", (draft_id,))
        if rows:
            break
        time.sleep(2)
    else:
        raise RuntimeError("Preview not ready; source ID retained, no automatic resend.")
    items = json.loads(rows[0][0])
    assert rows[0][1] == "gemma3:4b"
    assert len(items) == 3 and all(i["project"] == "ai-assistant" for i in items), items
    assert {i["status"] for i in items} == {"DONE", "IN_PROGRESS", "NOT_STARTED"}, items
    assert next(i["progress"] for i in items if i["status"] == "IN_PROGRESS") == 45, items
    # Never publish synthetic content unless the visible task names retain the label.
    assert all("테스트" in i["task"] or "검증용 가상" in i["task"] for i in items), "Synthetic labels missing; no publication."
    reply_id = "draft" + hashlib.sha256(f"{room}:{source}".encode()).hexdigest()[:24]
    preview = api.call("GET", "chat.getMessage", params={"msgId": reply_id})["message"]["msg"]
    action_id = "action" + hashlib.sha256(f"{room}:{source}".encode()).hexdigest()[:24]
    actions = api.call("GET", "chat.getMessage", params={"msgId": action_id})["message"]["msg"]
    assert "**[업무목록]**" in preview and "45%" in preview
    assert "127.0.0.1" not in preview and "`보고`" not in preview
    assert "`보고`" in actions and "보고 내용 수정하기" in actions and "**[업무목록]**" not in actions
    assert "진행률 미기재" not in preview and "100%" not in preview
    output.update(items=items, preview=preview, actions=actions, model=rows[0][1], preview_verified=True)
    output_file.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Actual personal-room preview verified.", flush=True)
    if args.publish:
        # Bare command is only safe if this is the only displayed, unposted draft.
        pending = query("SELECT d.id FROM chat_drafts d JOIN chat_draft_revisions r ON r.draft_id=d.id WHERE d.room_id=? AND d.author_id=? AND r.action='CHAT_PREVIEW' AND NOT EXISTS(SELECT 1 FROM chat_publications p WHERE p.draft_id=d.id AND p.state='SENT')", (room, api.user_id))
        command = "보고" if pending == [(draft_id,)] else "보고 " + draft_id[:8]
        command_id = "pubtest" + uuid.uuid4().hex[:18]
        api.call("POST", "chat.sendMessage", {"message": {"_id": command_id, "rid": room, "msg": command}, "previewUrls": []})
        output.update(command=command, command_id=command_id)
        output_file.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
        print("Explicit synthetic publication command sent.", flush=True)
        for _ in range(90):
            rows = query("SELECT state,message_id,text FROM chat_publications WHERE draft_id=?", (draft_id,))
            if rows and rows[0][0] == "SENT":
                break
            time.sleep(2)
        else:
            raise RuntimeError("Publication not verified; inspect saved command, do not recreate report.")
        published = api.call("GET", "chat.getMessage", params={"msgId": rows[0][1]})["message"]
        assert published["rid"] == cfg["channels"]["reports"]["room_id"] and published["msg"] == rows[0][2]
        assert published["msg"].split("\n\n작성자:")[0] in preview
        assert query("SELECT COUNT(*) FROM reports")[0][0] == before
        output.update(published=True, published_message_id=rows[0][1], verified=True)
    output_file.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
