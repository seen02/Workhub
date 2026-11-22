import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.models import ChatDraftRevision, ChatPublication, Report
from app.rocketchat.chat_publication import mark_displayed, personal_preview, personal_actions, publish_from_chat, authorize_chat_target
from app.rocketchat.commands import command_for
from app.rocketchat.project_match import suggest_project
from app.rocketchat import review_app
from app.rocketchat.review_app import LinkLogin, quick_publish
from app.rocketchat.review_service import save_review
from test_chat_review import db, USER, make_draft, edit, count
from test_chat_publication import personal, TARGET
from test_chat_easy import message


def shown(db, source="source1"):
    d = make_draft(db, source, "업무 비서 AI Agent 자료 조사 완료. 화면 수정 중.")
    mark_displayed(db, message(identity=source))
    return d


def send(db, text="보고", identity="publish1", deliver=lambda row: None, authorize=lambda: None, **changes):
    return publish_from_chat(db, message(text, identity, **changes), TARGET, authorize, deliver)


@pytest.mark.parametrize("text", ["보고", "!보고"])
def test_publish_commands(text):
    assert command_for(message(text), "room1", {"poc-employee"}, "bot") == ("publish", "")
    assert command_for(message(text, tmid="thread"), "room1", {"poc-employee"}, "bot") is None


def test_report_code_is_not_a_selection_command():
    assert command_for(message("보고 1234abcd"), "room1", {"poc-employee"}, "bot") == ("report", "1234abcd")


def test_display_preview_and_publish_same_body(db, personal):
    d = shown(db)
    text = personal_preview(d, "gemma3:4b", 1.5)
    actions = personal_actions(d, "gemma3:4b", 1.5, "http://edit", "http://publish")
    assert "**[업무목록]**" in text and "(✅ 완료)" in text
    assert "127.0.0.1" not in text and "`보고`" not in text and "내용 수정하기" not in text
    assert "`보고`" in actions and "이대로 보고" in actions and "내용 수정" in actions
    assert "http://publish" in actions and "8자리" not in actions and "**[업무목록]**" not in actions
    assert "진행률 미기재" not in text and "100%" not in text
    before = d.current_data
    deliveries = []
    assert "게시했습니다" in send(db, deliver=lambda r: deliveries.append(r.text))
    assert len(deliveries) == 1 and d.current_data == before and d.version == 2
    assert deliveries[0].split("\n\n작성자:")[0] in text
    assert count(db, Report) == 0
    shown(db, "source2")
    assert "중복" in send(db, deliver=lambda r: pytest.fail("duplicate"))
    assert count(db, ChatPublication) == 1


def test_multiple_previews_publish_latest_without_code(db, personal):
    make_draft(db, "old")
    a = shown(db, "source1")
    b = shown(db, "source2")
    assert "게시했습니다" in send(db)
    assert count(db, ChatPublication) == 1
    assert a.state == "DRAFT" and b.state == "CONFIRMED"


def test_old_unseen_draft_does_not_publish(db, personal):
    make_draft(db)
    assert "새 초안이 없습니다" in send(db)
    assert count(db, ChatPublication) == 0


@pytest.mark.parametrize("change", [{"u": {"_id": "other", "username": "other"}}, {"rid": "other"}])
def test_other_identity_never_publishes(db, personal, change):
    shown(db)
    assert "새 초안이 없습니다" in send(db, **change)
    assert count(db, ChatPublication) == 0


def test_web_edit_requires_web_confirmation(db, personal):
    d = shown(db)
    change = edit(d)
    change.items[0].task = "웹에서 바꾼 제목"
    save_review(db, d, USER, change, False)
    assert "웹에서 수정" in send(db)
    assert count(db, ChatPublication) == 0


@pytest.mark.parametrize("field,value", [("project", None), ("status", "UNKNOWN")])
def test_incomplete_preview_requires_web(db, personal, field, value):
    d = make_draft(db)
    items = json.loads(d.current_data)
    items[0][field] = value
    d.current_data = json.dumps(items)
    db.commit()
    mark_displayed(db, message(identity=d.message_id))
    assert "확인해 주세요" in send(db)
    assert d.state == "DRAFT"


def test_request_before_preview_and_import_blocked(db, personal):
    d = shown(db)
    assert "표시하기 전에" in send(db, ts="2000-01-01T00:00:00Z")
    assert d.state == "DRAFT"
    other = make_draft(db, "import")
    db.add(ChatDraftRevision(draft_id=other.id, version=1, actor_id=USER["_id"], action="IMPORT",
        before_data="[]", after_data=other.current_data, reason="과거 보고"))
    db.commit()
    mark_displayed(db, message(identity="import"))
    assert not db.scalar(select(ChatDraftRevision).where(ChatDraftRevision.draft_id == other.id,
        ChatDraftRevision.action == "CHAT_PREVIEW"))


def test_network_failure_retry_binds_same_report(db, personal):
    d = shown(db)
    sent_ids = []
    def fail(row):
        sent_ids.append(row.message_id)
        raise TimeoutError()
    with pytest.raises(HTTPException): send(db, deliver=fail)
    other = shown(db, "source2")
    assert db.scalar(select(ChatPublication)).state == "PENDING"
    assert "게시했습니다" in send(db, deliver=lambda r: sent_ids.append(r.message_id))
    assert len(set(sent_ids)) == 1 and other.state == "DRAFT"


def test_new_command_retries_pending_without_code(db, personal):
    d = shown(db)
    def fail(row): raise TimeoutError()
    with pytest.raises(HTTPException): send(db, deliver=fail)
    assert "게시했습니다" in send(db, "보고", "retry2")
    assert count(db, ChatPublication) == 1


def test_quick_publish_confirms_exact_visible_preview_once(db, personal, monkeypatch):
    d = shown(db)
    delivered = []
    monkeypatch.setattr(review_app, "_quick_publish_identity", lambda session, token: (d, USER, {}))
    monkeypatch.setattr(review_app, "config", lambda: personal)
    monkeypatch.setattr(review_app, "publish_target", lambda user, headers: TARGET)

    class API:
        client = SimpleNamespace(close=lambda: None)

        def __init__(self, config):
            pass

    monkeypatch.setattr("app.rocketchat.worker.ChatAPI", API)
    monkeypatch.setattr("app.rocketchat.delivery.deliver_publication",
                        lambda api, row: delivered.append(row.message_id))
    first = quick_publish(LinkLogin(token="x" * 20), db)
    second = quick_publish(LinkLogin(token="x" * 20), db)
    assert first["state"] == "SENT" and not first["already_sent"]
    assert second["already_sent"] and delivered == [db.scalar(select(ChatPublication)).message_id]
    assert d.state == "CONFIRMED" and d.version == 2


def test_quick_publish_rejects_changed_preview(db, personal, monkeypatch):
    d = shown(db)
    changed = edit(d)
    changed.items[0].task = "직원이 웹에서 바꾼 업무"
    save_review(db, d, USER, changed, False)
    monkeypatch.setattr(review_app, "_quick_publish_identity", lambda session, token: (d, USER, {}))
    with pytest.raises(HTTPException) as error:
        quick_publish(LinkLogin(token="x" * 20), db)
    assert error.value.status_code == 409 and count(db, ChatPublication) == 0


def test_authorization_before_save(db, personal):
    d = shown(db)
    def deny(): raise HTTPException(403, "denied")
    with pytest.raises(HTTPException): send(db, authorize=deny)
    assert d.state == "DRAFT" and count(db, ChatPublication) == 0


def test_target_requires_requesting_employee_membership(personal):
    cfg = {**personal, "personal_owner": "poc-employee", "team_id": "team",
           "room_type": "d", "username": "report-bot"}
    room = {"_id": "shared", "t": "p", "teamId": "team"}
    def denied(method, endpoint, **kwargs):
        if endpoint == "im.members":
            return {"members": [{"_id": USER["_id"], "username": USER["username"]},
                                {"_id": "bot", "username": "report-bot"}], "total": 2}
        if endpoint == "groups.info":
            return {"group": room}
        return {"members": [{"_id": "bot", "username": "report-bot"}], "total": 1}
    api = SimpleNamespace(call=denied)
    with pytest.raises(HTTPException): authorize_chat_target(api, cfg, USER, "room1")
    api.call = lambda method, endpoint, **kwargs: ({"group": room} if endpoint == "groups.info" else {
        "members": ([{"_id": USER["_id"], "username": USER["username"]},
                     {"_id": "bot", "username": "report-bot"}] if endpoint == "im.members" else
                    [{"_id": USER["_id"], "username": USER["username"]}]),
        "total": 2 if endpoint == "im.members" else 1,
    })
    authorize_chat_target(api, cfg, USER, "room1")
    room["encrypted"] = True
    with pytest.raises(HTTPException): authorize_chat_target(api, cfg, USER, "room1")


@pytest.mark.parametrize("raw,evidence,expected", [
    ("Agent 개발 중", "개발 중", None),
    ("업무 비서 Agent 개발 중. 화면 수정 완료", "화면 수정 완료", "ai-assistant"),
    ("업무 비서 개발 완료. 공간정보 검색 중", "공간정보 검색 중", "spatial-agent"),
    ("업무 비서 개발 완료. GIS 작업 중. 문서 정리 중", "문서 정리 중", None),
    ("업무 비서와 GIS 연계", "업무 비서와 GIS 연계", None),
])
def test_project_source_hints(raw, evidence, expected):
    assert suggest_project(raw, evidence) == expected
