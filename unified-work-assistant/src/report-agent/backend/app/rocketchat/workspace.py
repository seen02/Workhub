"""Server-owned room mapping. Never accept a publish destination from a browser/LLM."""
import json
import os
from pathlib import Path
from urllib.parse import quote

LOCAL = Path(os.getenv(
    "ROCKETCHAT_LOCAL_PATH",
    Path(__file__).resolve().parents[3] / "rocketchat" / ".local",
))
PUBLIC_URL = os.getenv("ROCKETCHAT_PUBLIC_URL", "http://127.0.0.1:3000").rstrip("/")
PROJECTS = {"ai-assistant": "AI업무비서 개발 프로젝트", "spatial-agent": "공간정보 Agent 프로젝트"}


def settings():
    return json.loads((LOCAL / "bot.json").read_text(encoding="utf-8"))


def source_url(room_id, message_id):
    name = "poc-reports"
    try:
        cfg = settings()
        direct = next((r for r in cfg.get("direct_rooms", {}).values()
                       if r["room_id"] == room_id), None)
        if direct:
            return f"{PUBLIC_URL}/direct/{quote(cfg['username'], safe='')}?msg={quote(message_id, safe='')}"
        rooms = (list(cfg.get("personal_rooms", {}).values())
                 + list(cfg.get("legacy_personal_rooms", {}).values())
                 + list(cfg.get("channels", {}).values()))
        matched = next((r for r in rooms if r["room_id"] == room_id), None)
        if matched:
            name = matched["name"]
        elif cfg.get("dm_mode"):
            return f"{PUBLIC_URL}/direct/{quote(cfg['username'], safe='')}?msg={quote(message_id, safe='')}"
    except FileNotFoundError:
        pass
    return f"{PUBLIC_URL}/group/{quote(name, safe='')}?msg={quote(message_id, safe='')}"


def room_url(room):
    if room.get("type") == "d":
        return f"{PUBLIC_URL}/direct/" + quote(room["name"], safe="")
    return f"{PUBLIC_URL}/group/" + quote(room["name"], safe="")


def is_personal(room_id):
    try:
        cfg = settings()
        return any(r["room_id"] == room_id for group in (
            cfg.get("personal_rooms", {}), cfg.get("legacy_personal_rooms", {}),
            cfg.get("direct_rooms", {})) for r in group.values())
    except FileNotFoundError:
        return False


def private_members_ok(data, author, bot):
    members = data.get("members", [])
    return (data.get("total", len(members)) == 2 and len(members) == 2
            and {m.get("username") for m in members} == {author, bot})
