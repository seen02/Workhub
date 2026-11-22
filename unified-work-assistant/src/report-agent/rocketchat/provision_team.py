"""Idempotent local-only team setup; no user report is posted or copied."""
import json
import hashlib
from setup import API, LOCAL, URL, employee_accounts


def paged_members(api, room_id):
    offset = 0
    found = []
    while True:
        result = api.call("GET", "groups.members", params={
            "roomId": room_id, "count": 100, "offset": offset,
        })
        page = result.get("members", [])
        found.extend(page)
        offset += len(page)
        if not page or offset >= result.get("total", offset):
            return found


def sync_personal_rooms(bot, member_names, bot_username):
    """Create/reuse one exact two-member report room for each employee."""
    offset = 0
    bot_rooms = []
    while True:
        result = bot.call("GET", "groups.list", params={"count": 100, "offset": offset})
        page = result.get("groups", [])
        bot_rooms.extend(page)
        offset += len(page)
        if not page or offset >= result.get("total", offset):
            break
    personal_rooms = {}
    for owner in sorted(member_names):
        personal_name = f"개인보고-{owner}"
        personal = next((room for room in bot_rooms if room.get("name") == personal_name), None)
        created = personal is None
        if not personal:
            personal = bot.call("POST", "groups.create", {
                "name": personal_name, "members": [owner],
            })["group"]
            bot_rooms.append(personal)
        members = bot.call("GET", "groups.members", params={"roomId": personal["_id"], "count": 3})
        expected = {owner, bot_username}
        actual = {user["username"] for user in members.get("members", [])}
        if members.get("total") != 2 or actual != expected:
            raise RuntimeError(f"Personal room for {owner} has unexpected members; no memberships changed")
        if personal.get("teamId"):
            raise RuntimeError(f"Personal room for {owner} must remain outside the team")
        if created:
            bot.call("POST", "groups.setTopic", {"roomId": personal["_id"],
                "topic": "본인 + report-bot | 보고 업무내용 → AI 구조화 → 확인·수정 → 업무보고에 게시"})
        personal_rooms[owner] = {"room_id": personal["_id"], "name": personal["name"], "type": "p"}
    return personal_rooms


def main():
    credentials = json.loads((LOCAL / "credentials.json").read_text(encoding="utf-8"))
    admin = API(**credentials["admin"])
    employees = [(account, API(**account)) for _, account, _ in employee_accounts(credentials)]
    cfg = json.loads((LOCAL / "bot.json").read_text(encoding="utf-8"))
    name_rule = admin.call("GET", "settings/UTF8_Channel_Names_Validation")["value"]
    if name_rule == "[0-9a-zA-Z-_.]+":
        response = admin.client.post("/api/v1/settings/UTF8_Channel_Names_Validation", json={"value": "[0-9a-zA-Z가-힣ㄱ-ㅎㅏ-ㅣ-_.]+"})
        if response.status_code == 400 and response.json().get("details", {}).get("method") == "password":
            response = admin.client.post("/api/v1/settings/UTF8_Channel_Names_Validation",
                json={"value": "[0-9a-zA-Z가-힣ㄱ-ㅎㅏ-ㅣ-_.]+"}, headers={"X-2fa-Method": "password",
                "X-2fa-Code": hashlib.sha256(credentials["admin"]["password"].encode()).hexdigest()})
        if response.status_code != 200:
            raise RuntimeError("Channel name setting requires administrator reauthentication")
    elif name_rule != "[0-9a-zA-Z가-힣ㄱ-ㅎㅏ-ㅣ-_.]+":
        raise RuntimeError("Custom channel-name rule found; review it before changing")
    employee_names = [account["username"] for account, _ in employees]
    bot_name = credentials["bot"]["username"]
    people = employee_names + [bot_name]
    user_ids = {name: admin.call("GET", "users.info", params={"username": name})["user"]["_id"]
                for name in people}
    response = admin.client.get("/api/v1/teams.info", params={"teamName": "기술지원팀"})
    if response.status_code == 200 and response.json().get("success"):
        team = response.json()["teamInfo"]
    elif response.status_code in (400, 404):
        created = admin.client.post("/api/v1/teams.create", json={
            "name": "기술지원팀", "type": 1, "members": list(user_ids.values()),
        })
        if created.status_code != 200:
            raise RuntimeError("teams.create: " + str(created.json().get("error", "request failed")))
        team = created.json()["team"]
    else:
        raise RuntimeError("Unable to inspect team")
    team_members = admin.call("GET", "teams.members", params={"teamId": team["_id"], "count": 100})
    existing_team_ids = {member["user"]["_id"] for member in team_members.get("members", [])}
    missing_team_members = [
        {"userId": user_ids[name], "roles": ["member"]}
        for name in people if user_ids[name] not in existing_team_ids
    ]
    if missing_team_members:
        admin.call("POST", "teams.addMembers", {
            "teamId": team["_id"], "members": missing_team_members,
        })
    channels = {}
    definitions = [
        ("ai-assistant", "AI업무비서-개발-project", "AI업무비서 개발 프로젝트 · 논의·자료 공유 · 자동 보고 수집 없음"),
        ("spatial-agent", "공간정보-Agent-project", "공간정보 Agent 프로젝트 · 논의·자료 공유 · 자동 보고 수집 없음"),
        ("reports", "업무보고", "확정 보고 공유 + 팀 업무 질문 | 일반 대화와 미확정 초안은 조회 제외"),
    ]
    for key, name, topic in definitions:
        rooms = admin.call("GET", "groups.list", params={"count": 100})["groups"]
        room = next((r for r in rooms if r.get("name") == name), None)
        if not room:
            room = admin.call("POST", "groups.create", {"name": name, "members": people})["group"]
        members = admin.call("GET", "groups.members", params={"roomId": room["_id"], "count": 100})
        present = {member["username"] for member in members.get("members", [])}
        for username in people:
            if username not in present:
                admin.call("POST", "groups.invite", {
                    "roomId": room["_id"], "userId": user_ids[username],
                })
        if room.get("teamId") and room["teamId"] != team["_id"]:
            raise RuntimeError("Existing channel belongs to another team")
        if not room.get("teamId"):
            admin.call("POST", "teams.addRooms", {"teamId": team["_id"], "rooms": [room["_id"]]})
        admin.call("POST", "groups.setTopic", {"roomId": room["_id"], "topic": topic})
        channels[key] = {"room_id": room["_id"], "name": room["name"]}
    # The bot owns each two-member private room. This lets an administrator add a
    # team member and rerun this script without knowing the employee password.
    bot = API(**credentials["bot"])
    report_members = paged_members(admin, channels["reports"]["room_id"])
    eligible_names = sorted({member["username"] for member in report_members
                             if member.get("username") not in {
                                 bot_name, credentials["admin"]["username"],
                             }})
    personal_rooms = sync_personal_rooms(bot, eligible_names, bot_name)
    cfg.setdefault("legacy_room_id", cfg["room_id"])
    if cfg.get("direct_rooms"):
        cfg.setdefault("legacy_direct_rooms", cfg["direct_rooms"])
    cfg.update(team_id=team["_id"], channels=channels,
               personal_rooms=personal_rooms, dm_mode=False,
               personal_room_excluded_usernames=[credentials["admin"]["username"]],
               allowed_usernames=sorted({member["username"] for member in report_members
                                         if member.get("username") != bot_name}),
               room_id=personal_rooms[eligible_names[0]]["room_id"] if eligible_names else channels["reports"]["room_id"])
    # The shared 업무보고 room is now the single place for team and manager
    # lookup questions. Keep any old room history in Rocket.Chat, but do not
    # provision or subscribe the bot to a separate manager room.
    cfg.pop("manager_room", None)
    (LOCAL / "bot.json").write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"team": "기술지원팀", "channels": channels,
                      "personal_rooms": len(personal_rooms), "dm_mode": False,
                      "query_room": channels["reports"]["name"],
                      "employee_count": len(employee_names), "reports_copied": 0}, ensure_ascii=False))


if __name__ == "__main__":
    main()
