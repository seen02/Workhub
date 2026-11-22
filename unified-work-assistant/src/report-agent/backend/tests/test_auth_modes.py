from types import SimpleNamespace

import jwt

from app.config import get_settings


def test_jwt_mode_requires_bearer_token(client, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "auth_mode", "jwt")
    monkeypatch.setattr(settings, "jwt_jwks_url", "https://sso.example.test/.well-known/jwks.json")
    monkeypatch.setattr(settings, "jwt_issuer", "https://sso.example.test")
    monkeypatch.setattr(settings, "jwt_audience", "flowmate")
    response = client.get("/api/auth/session")
    assert response.status_code == 401


def test_jwt_claims_map_to_employee_identity(client, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "auth_mode", "jwt")
    monkeypatch.setattr(settings, "jwt_jwks_url", "https://sso.example.test/.well-known/jwks.json")
    monkeypatch.setattr(settings, "jwt_issuer", "https://sso.example.test")
    monkeypatch.setattr(settings, "jwt_audience", "flowmate")

    fake_client = SimpleNamespace(get_signing_key_from_jwt=lambda _: SimpleNamespace(key="public-key"))
    monkeypatch.setattr("app.auth._jwks_client", lambda _: fake_client)
    monkeypatch.setattr(jwt, "decode", lambda *args, **kwargs: {"sub": "user-1", "role": "employee", "employee_id": 1})

    response = client.get("/api/auth/session", headers={"Authorization": "Bearer test-token"})
    assert response.status_code == 200
    assert response.json() == {"mode": "jwt", "role": "employee", "employee_id": 1}
