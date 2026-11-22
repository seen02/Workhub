"""Synchronize employee personal-report rooms from the shared report channel."""
import json

from provision_team import paged_members, sync_personal_rooms
from setup import API, LOCAL


def main():
    credentials = json.loads((LOCAL / "credentials.json").read_text(encoding="utf-8"))
    settings_path = LOCAL / "bot.json"
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    reports = settings.get("channels", {}).get("reports")
    if not reports:
        raise RuntimeError("Run provision_team.py before employee room synchronization")
    admin = API(**credentials["admin"])
    bot = API(**credentials["bot"])
    members = paged_members(admin, reports["room_id"])
    excluded = {credentials["bot"]["username"], credentials["admin"]["username"]}
    employees = sorted({member["username"] for member in members
                        if member.get("username") not in excluded})
    rooms = sync_personal_rooms(bot, employees, credentials["bot"]["username"])
    settings.update(personal_rooms=rooms, dm_mode=False,
                    personal_room_excluded_usernames=[credentials["admin"]["username"]],
                    allowed_usernames=sorted({member["username"] for member in members
                                              if member.get("username") != credentials["bot"]["username"]}))
    if employees:
        settings["room_id"] = rooms[employees[0]]["room_id"]
    temporary = settings_path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(settings_path)
    print(json.dumps({"employees": len(employees), "personal_rooms": len(rooms),
                      "worker_restart_required": False}, ensure_ascii=False))


if __name__ == "__main__":
    main()
