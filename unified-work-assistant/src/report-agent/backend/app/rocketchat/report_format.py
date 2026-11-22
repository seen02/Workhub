"""Company report layout; presentation only, no state/progress inference."""
from datetime import timedelta, timezone
from .draft import safe_text

REPORT_PROJECTS = {
    "ai-assistant": "로켓챗 기반 업무 비서 AI Agent 개발",
    "spatial-agent": "자연어 기반 GIS 분석 프로젝트 진행 방향 정리",
}
STATUS_LABELS = {"DONE": "✅ 완료", "IN_PROGRESS": "🔄 진행중", "NOT_STARTED": "⏳ 예정",
                 "DELAYED": "⚠️ 지연", "UNKNOWN": "❔ 상태 확인 필요"}


def format_report(items, submitted_at, *, project_names=None):
    kst = timezone(timedelta(hours=9))
    when = submitted_at.replace(tzinfo=kst) if submitted_at.tzinfo is None else submitted_at.astimezone(kst)
    clock = f"{when.hour}시" + (f" {when.minute}분" if when.minute else "")
    names = REPORT_PROJECTS if project_names is None else project_names
    groups = [(key, safe_text(title), [i for i in items if i.get("project") == key]) for key, title in names.items()]
    unknown = [i for i in items if i.get("project") not in names]
    if unknown:
        groups.append((None, "프로젝트 미선택", unknown))
    groups = [group for group in groups if group[2]]
    lines = ["**[업무목록]**", *["- " + title for _, title, _ in groups], "",
             f"**[{when.month}월 {when.day}일 {'월화수목금토일'[when.weekday()]}요일 : {clock}]**"]
    for _, title, tasks in groups:
        lines.extend(["", f"**{title}**"])
        for index, item in enumerate(tasks, 1):
            state = STATUS_LABELS[item["status"]]
            if item["status"] == "IN_PROGRESS" and item.get("progress") is not None:
                state += f" {item['progress']}%"
            lines.append(f"{index}. {safe_text(item['task'])}({state})")
            if item.get("next_action"):
                lines.append("   다음 작업: " + safe_text(item["next_action"]))
            if item.get("issue"):
                lines.append("   이슈: " + safe_text(item["issue"]))
    return "\n".join(lines)
