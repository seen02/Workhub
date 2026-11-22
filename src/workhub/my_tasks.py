"""Read-only personal work inventory. No search, model, or Outline normalization."""
import logging
from datetime import datetime, timezone, timedelta, date

from . import outline, permissions, execution

log = logging.getLogger('workhub.my_tasks')
KST = timezone(timedelta(hours=9))
GROUPS = ('overdue', 'today', 'upcoming', 'undated')
LABELS = {'overdue': '🔴 기한 초과', 'today': ':workhub_orange_circle: 오늘 마감',
          'upcoming': '🔵 앞으로 할 업무', 'undated': '⚪ 마감일 미정'}


def personal(task, user, today):
    """Return one actionable task, based on MY criteria, not administrator powers."""
    email = user['email'].strip().lower()
    fields = task['fields']
    items = task.get('criteria', [])
    mine = [i for i in items if i['owner'].strip().lower() == email]
    remaining = [i for i in mine if i['state'] != '완료']
    if items:
        if not remaining:
            return None
    elif fields.get('owner', '').strip().lower() != email or fields['status'] == '완료':
        return None
    due = fields.get('due')
    due_date = date.fromisoformat(due) if due and due != '미정' else None
    group = ('undated' if due_date is None else 'overdue' if due_date < today
             else 'today' if due_date == today else 'upcoming')
    return {**task, 'mine': mine, 'remaining': remaining, 'group': group,
            'late_days': (today - due_date).days if group == 'overdue' else 0}


@execution.operation('my_tasks')
def collect(user, now=None):
    now = (now or datetime.now(KST)).astimezone(KST)
    projects = permissions.projects(user)  # An ACL failure must not become an empty result.
    rows, failures, invalid, seen = [], [], 0, set()
    for project in projects:
        try:
            tasks, errors = outline.read_project_tasks(user, project['id'])
        except Exception as ex:
            # Do not expose raw API errors or any inaccessible document contents.
            execution.count('my_tasks.project_failure')
            log.warning('project_read_failed type=%s', type(ex).__name__)
            failures.append(project['id'])
            continue
        invalid += errors
        for task in tasks:
            if task['id'] in seen:
                continue
            seen.add(task['id'])
            try:
                row = personal(task, user, now.date())
            except (ValueError, KeyError, TypeError):
                invalid += 1
                continue
            if row:
                rows.append(row)
    rows.sort(key=lambda t: (GROUPS.index(t['group']), t['fields'].get('due') or '미정',
                             t['collectionName'], t['title'], t['id']))
    return {'rows': rows, 'counts': {g: sum(t['group'] == g for t in rows) for g in GROUPS},
            'at': now.isoformat(), 'project_count': len(projects), 'failed': len(failures),
            'invalid': invalid, 'complete': not failures and not invalid,
            'all_failed': bool(projects) and len(failures) == len(projects)}
