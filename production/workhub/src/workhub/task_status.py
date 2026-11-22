"""Document status stays authoritative; manual mode survives edits to its label."""
import json
import re
from . import domain, criteria, human_tasks, store

MANUAL = '상태 관리: 칸반'


def labelled(text):
    header = re.split(r'^## ', domain.source_text(text), maxsplit=1, flags=re.M)[0]
    return bool(re.search(r'^[ \t]*(?:\*\*)?상태 관리:(?:\*\*)?[ \t]*칸반[ \t]*$', header, re.M))


def manual(text, document_id=''):
    if labelled(text):return True
    if not document_id:return False
    if store.get('task-status-mode:' + document_id):return True
    # Upgrade existing boards using the last recorded source, never its status.
    with store.db() as connection:
        row = connection.execute('SELECT body FROM tasks WHERE id=?', (document_id,)).fetchone()
    return bool(row and labelled(json.loads(row['body']).get('text','')))


def remember(document_id, text, kanban=False):
    if kanban or manual(text,document_id):
        store.put('task-status-mode:' + document_id, {'mode':'manual'})


def mark_manual(text):
    if manual(text):return text
    live = domain.source_text(text)
    head, *tail = re.split(r'(?=^## )', live, maxsplit=1, flags=re.M)
    head = re.sub(r'^([ \t]*(?:\*\*)?상태:(?:\*\*)?[^\n]*)$',
                  lambda m: m[0] + '\n\n' + MANUAL, head, count=1, flags=re.M)
    return head + ''.join(tail) + text[len(live):]


def summary(text, items, preserve_human=False, document_id=''):
    result = criteria.rollup(items)
    status = domain.parse(text)['status']
    if manual(text,document_id) or (preserve_human and human_tasks.is_human(text)
                        and result['status'] != '완료' and status in ('진행 중', '보류', '지연')):
        result['status'] = status
    return result
