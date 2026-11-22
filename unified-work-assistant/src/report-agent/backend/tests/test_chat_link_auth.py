from types import SimpleNamespace

import pytest

from app.rocketchat.link_auth import (issue_link, issue_manager_link, issue_session,
                                      verify_link, verify_manager_link, verify_session)
from app.rocketchat import review_app


def test_signed_review_link_is_scoped_and_expires(tmp_path):
    entity = SimpleNamespace(id="a" * 64, author_id="employee1", room_id="room1")
    key = tmp_path / "link.key"
    token = issue_link(entity, lifetime=60, now=1000, key_path=key)
    assert verify_link(token, now=1030, key_path=key) == {
        "draft": entity.id, "user": "employee1", "room": "room1", "exp": 1060,
    }
    with pytest.raises(ValueError):
        verify_link(token[:-1] + ("a" if token[-1] != "a" else "b"), now=1030, key_path=key)
    with pytest.raises(ValueError):
        verify_link(token, now=1061, key_path=key)


def test_signed_manager_link_is_short_lived_and_purpose_scoped(tmp_path):
    key = tmp_path / "manager-link.key"
    token = issue_manager_link("admin1", "poc-admin", lifetime=120, now=1000, key_path=key)
    assert verify_manager_link(token, now=1060, key_path=key) == {
        "purpose": "manager-dashboard", "user": "admin1", "username": "poc-admin", "exp": 1120,
    }
    with pytest.raises(ValueError):
        verify_link(token, now=1060, key_path=key)
    with pytest.raises(ValueError):
        verify_manager_link(token, now=1121, key_path=key)


def test_app_session_is_purpose_scoped_and_expires(tmp_path):
    key = tmp_path / "session.key"
    token = issue_session("employee1", "poc-employee", "dm1", now=1000, lifetime=60, key_path=key)
    assert verify_session(token, now=1030, key_path=key) == {
        "purpose": "review-session", "user": "employee1", "username": "poc-employee",
        "room": "dm1", "exp": 1060,
    }
    with pytest.raises(ValueError):
        verify_session(token, purpose="team-session", now=1030, key_path=key)
    with pytest.raises(ValueError):
        verify_session(token, now=1061, key_path=key)


def test_validated_rocket_session_is_reused_briefly(monkeypatch):
    review_app.AUTH_CACHE.clear()
    cfg = {"username": "report-bot", "team_id": "team1", "dm_mode": True,
           "channels": {"reports": {"room_id": "reports", "name": "업무보고"}}}
    calls = []
    def fake_request(method, endpoint, **kwargs):
        calls.append(endpoint)
        if endpoint == "me":
            return {"_id": "employee1", "username": "poc-employee"}
        if endpoint == "groups.info":
            return {"group": {"_id": "reports", "name": "업무보고", "t": "p", "teamId": "team1"}}
        if endpoint == "groups.members":
            return {"members": [{"_id": "employee1", "username": "poc-employee"}], "total": 1}
        if endpoint == "im.create":
            return {"room": {"rid": "room1"}}
        return {"members": [{"_id": "employee1", "username": "poc-employee"},
                            {"_id": "bot1", "username": "report-bot"}], "total": 2}
    monkeypatch.setattr(review_app, "config", lambda: cfg)
    monkeypatch.setattr(review_app, "chat_request", fake_request)
    first = review_app.resolve_user("employee1", "token")
    second = review_app.resolve_user("employee1", "token")
    expected = ["me", "groups.info", "groups.members", "im.create", "im.members"]
    assert first == second and calls == expected
    review_app.resolve_user("employee1", "different-token")
    assert calls == expected * 2
    review_app.AUTH_CACHE.clear()
