"""Local-only Rocket.Chat provisioning; never prints passwords or auth tokens."""
from __future__ import annotations

import argparse
import json
import secrets
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent
LOCAL = ROOT / ".local"
URL = "http://127.0.0.1:3000"
EMPLOYEE_SPECS = (
    ("employee", "poc-employee", "테스트 직원 1"),
    ("employee2", "poc-employee-2", "테스트 직원 2"),
    ("employee3", "poc-employee-3", "테스트 직원 3"),
    ("employee4", "poc-employee-4", "테스트 직원 4"),
)


def employee_accounts(credentials):
    """Return configured PoC employees while preserving the original account."""
    return [(key, credentials[key], name) for key, _, name in EMPLOYEE_SPECS if key in credentials]


def init() -> None:
    LOCAL.mkdir(exist_ok=True)
    path = LOCAL / "credentials.json"
    if path.exists():
        credentials = json.loads(path.read_text(encoding="utf-8"))
    else:
        credentials = {
            "admin": {"username": "poc-admin", "password": secrets.token_urlsafe(24)},
            "bot": {"username": "report-bot", "password": secrets.token_urlsafe(24)},
        }
    for key, username, _ in EMPLOYEE_SPECS:
        credentials.setdefault(key, {"username": username, "password": secrets.token_urlsafe(18)})
    credentials.setdefault(
        "report_database",
        {"username": "work_agent", "password": secrets.token_urlsafe(32)},
    )
    path.write_text(json.dumps(credentials, indent=2), encoding="utf-8")
    (LOCAL / "compose.env").write_text(
        "\n".join(
            (
                f"RC_ADMIN_PASSWORD={credentials['admin']['password']}",
                f"REPORT_DB_PASSWORD={credentials['report_database']['password']}",
                "",
            )
        ),
        encoding="utf-8",
    )
    print("Local credentials ready in rocketchat/.local/credentials.json (git-ignored).")


class API:
    def __init__(self, username: str, password: str):
        self.client = httpx.Client(base_url=URL, timeout=30, trust_env=False)
        data = self.call("POST", "login", {"user": username, "password": password})["data"]
        self.user_id = data["userId"]
        self.client.headers.update({"X-User-Id": self.user_id, "X-Auth-Token": data["authToken"]})

    def call(self, method: str, endpoint: str, body=None, params=None):
        for attempt in range(6):
            response = self.client.request(method, f"/api/v1/{endpoint}", json=body, params=params)
            if response.status_code != 429 or attempt == 5:
                break
            retry_after = response.headers.get("Retry-After", "")
            delay = float(retry_after) if retry_after.replace(".", "", 1).isdigit() else 10.0
            time.sleep(max(1.0, min(delay, 30.0)))
        if response.status_code >= 400:
            # Do not dump login payloads, request headers, or credentials.
            raise RuntimeError(f"{endpoint}: HTTP {response.status_code}; {response.json().get('errorType', '')}")
        result = response.json()
        if result.get("success") is False:
            raise RuntimeError(f"{endpoint}: unsuccessful")
        return result


def provision() -> None:
    credentials = json.loads((LOCAL / "credentials.json").read_text(encoding="utf-8"))
    api = API(**credentials["admin"])
    accounts = employee_accounts(credentials) + [("bot", credentials["bot"], "업무보고 AI · 초안")]
    for key, account, name in accounts:
        response = api.client.get("/api/v1/users.info", params={"username": account["username"]})
        if response.status_code == 200 and response.json().get("success"):
            continue
        if response.status_code not in (400, 404):
            raise RuntimeError(f"users.info: HTTP {response.status_code}")
        api.call("POST", "users.create", {
            **account, "name": name, "email": f"{account['username']}@example.invalid",
            "roles": ["user"], "verified": True, "joinDefaultChannels": False,
            "sendWelcomeEmail": False, "requirePasswordChange": False,
        })
    groups = api.call("GET", "groups.list")["groups"]
    room = next((group for group in groups if group.get("name") == "poc-reports"), None)
    employee_usernames = [account["username"] for _, account, _ in employee_accounts(credentials)]
    if not room:
        room = api.call("POST", "groups.create", {
            "name": "poc-reports", "members": employee_usernames + [credentials["bot"]["username"]],
        })["group"]
        api.call("POST", "groups.setTopic", {
            "roomId": room["_id"],
            "topic": "개발용 비공개 테스트방 | !보고 + 자유 형식 업무내용 → Gemma 초안 | 확정 저장·실제 업무 게시 아님",
        })
    bot_config = {
        "url": URL, "username": credentials["bot"]["username"],
        "password": credentials["bot"]["password"], "room_id": room["_id"],
        "allowed_usernames": employee_usernames + [credentials["admin"]["username"]],
    }
    existing_path = LOCAL / "bot.json"
    if existing_path.exists():
        previous = json.loads(existing_path.read_text(encoding="utf-8"))
        if previous.get("channels"):
            preserved = ("personal_rooms", "legacy_personal_rooms", "direct_rooms", "dm_mode",
                         "personal_room_excluded_usernames",
                         "channels", "team_id", "legacy_room_id", "room_id")
            bot_config.update({key: previous[key] for key in preserved if key in previous})
    (LOCAL / "bot.json").write_text(json.dumps(bot_config, ensure_ascii=False, indent=2), encoding="utf-8")
    login_lines = ["로컬 테스트 전용 / 외부 공유 금지"]
    for _, account, name in employee_accounts(credentials):
        room_name = bot_config.get("personal_rooms", {}).get(account["username"], {}).get(
            "name", f"개인보고-{account['username']}")
        login_lines.extend([
            "", name, f"주소: {URL}/group/{room_name}", f"아이디: {account['username']}",
            f"비밀번호: {account['password']}",
        ])
    login_lines.extend(["", "테스트 문장:",
                        "보고 오늘 업무비서 화면 검토를 완료했고 직원별 보고 분리 테스트는 60% 진행 중입니다."])
    (LOCAL / "LOGIN.txt").write_text("\n".join(login_lines) + "\n", encoding="utf-8")
    current_room = bot_config.get("personal_rooms", {}).get("poc-employee", {}).get("name", "poc-reports")
    print(f"Test accounts ready: {URL}/group/{current_room}")
    print("Login information: rocketchat/.local/LOGIN.txt")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["init", "provision"])
    args = parser.parse_args()
    init() if args.action == "init" else provision()
