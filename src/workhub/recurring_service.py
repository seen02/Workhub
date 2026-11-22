"""User-scoped recurring rules; the browser never supplies an execution identity."""
import hashlib
import json
import os
import time
import uuid
from datetime import date, timedelta
from fastapi import HTTPException
from . import outline, permissions, store, task_creation
from . import recurring_schedule as schedule, recurring_store as records


def enabled():
    return os.getenv('OUTLINE_RECURRING_ENABLED', 'false').lower() == 'true'


def context(user, cid, parent_id, write=False):
    permissions.project(user, cid)
    mapping = store.get('task-parent:' + cid)
    if not mapping or mapping['id'] != parent_id:
        raise HTTPException(409, '프로젝트의 현재 업무 목록에서 반복 업무를 관리하세요.')
    parent = outline.api('documents.info', {'id': parent_id}, missing_ok=True)
    if (not parent or parent.get('collectionId') != cid or parent.get('parentDocumentId')
            or not parent.get('publishedAt') or any(parent.get(k) for k in ('archivedAt', 'deletedAt', 'template'))):
        raise HTTPException(409, '업무 목록의 위치나 상태가 변경되었습니다.')
    if write:
        task_creation.context(user, cid, parent_id)


def visible(user, rule):
    return user.get('admin') or user['sub'] in (rule['creator_sub'], rule['executor_sub'])


def get(user, cid, parent_id, rule_id, write=False):
    context(user, cid, parent_id, write)
    rule = records.rule(rule_id)
    if not rule or rule['collection_id'] != cid or rule['parent_id'] != parent_id or not visible(user, rule):
        raise HTTPException(404, '반복 업무를 찾을 수 없습니다.')
    return rule


def public(rule, user=None):
    body = json.loads(rule['body'])
    body.setdefault('repeatCount', None)
    body.setdefault('taskStartOffset', 0)
    return {'id': rule['id'], 'revision': rule['revision'], 'state': rule['state'],
            'nextDate': rule['next_date'], 'reason': rule['reason'], 'settings': body,
            **schedule.describe(body),
            'createdAt': rule['created_at'], 'updatedAt': rule['updated_at'],
            'canManage': bool(user and visible(user, rule))}


def query(user, cid, parent_id, can_write):
    context(user, cid, parent_id)
    people = permissions.assignees(user, cid)
    with store.db() as c:
        rows = c.execute('SELECT * FROM recurring_rules WHERE collection_id=? AND parent_id=? '
                         "AND state<>'archived' ORDER BY created_at,id", (cid, parent_id)).fetchall()
    return {'rules': [public(dict(r), user) for r in rows if visible(user, r)], 'people': people,
            'viewer': {'admin': bool(user.get('admin')), 'email': user['email']},
            'canCreate': bool(can_write), 'today': schedule.now().date().isoformat(),
            'now': schedule.now().isoformat(), 'generationTime': '07:00', 'timezone': 'Asia/Seoul'}


def clean_settings(user, cid, body):
    allowed = {'title', 'ownerId', 'notes', 'criteria', 'frequency', 'weekday', 'monthDay',
               'startDate', 'repeatCount', 'taskStartOffset', 'dueOffset', 'unfinishedPolicy'}
    if not isinstance(body, dict) or set(body) - allowed:
        raise ValueError('지원하지 않는 반복 설정 항목입니다.')
    result = {**body}
    result.setdefault('repeatCount', None)
    result.setdefault('taskStartOffset', 0)
    title = str(result.get('title', '')).strip()
    if not title or len(title) > 120 or '\n' in title or '\r' in title:
        raise ValueError('업무명은 한 줄, 1~120자로 입력하세요.')
    result['title'] = title
    if not isinstance(result.get('notes', ''), str) or len(result.get('notes', '')) > 10000:
        raise ValueError('업무 내용은 10,000자 이내로 입력하세요.')
    result.setdefault('notes', '')
    schedule.validate(result)
    people = permissions.assignees(user, cid)
    owners = {p['id']: p for p in people}
    owner = owners.get(result.get('ownerId'))
    if not owner:
        raise HTTPException(403, '현재 프로젝트의 활성 구성원만 담당자로 지정할 수 있습니다.')
    if not user.get('admin') and owner['email'].lower() != user['email'].lower():
        raise HTTPException(403, '자신의 반복 업무만 등록할 수 있습니다.')
    items = result.get('criteria', [])
    if not isinstance(items, list) or len(items) > 40:
        raise ValueError('완료 기준은 40개 이내로 입력하세요.')
    cleaned = []
    for item in items:
        if not isinstance(item, dict) or set(item) != {'title', 'assigneeId'}:
            raise ValueError('완료 기준 형식을 확인하세요.')
        text = str(item['title']).strip()
        if not text or len(text) > 200 or '\n' in text or '\r' in text:
            raise ValueError('완료 기준은 한 줄, 1~200자로 입력하세요.')
        if item['assigneeId'] not in owners:
            raise HTTPException(403, '완료 기준 담당자는 현재 프로젝트의 활성 구성원이어야 합니다.')
        cleaned.append({'title': text, 'assigneeId': item['assigneeId']})
    result['criteria'] = cleaned
    return result


def preview(user, cid, parent_id, settings, today_mode='next'):
    context(user, cid, parent_id, True)
    settings = clean_settings(user, cid, settings)
    return {'occurrences': schedule.preview(settings, include_today=today_mode == 'now'),
            **schedule.describe(settings),
            'todayEligible': schedule.matches(settings, schedule.now().date()),
            'todayTimePassed': schedule.now() >= schedule.scheduled(schedule.now().date())}


def receipt(c, request_id, user, fingerprint):
    old = c.execute('SELECT * FROM recurring_requests WHERE id=?', (request_id,)).fetchone()
    if old:
        if old['actor'] != user['sub'] or old['fingerprint'] != fingerprint:
            raise HTTPException(409, '같은 요청 번호의 내용이나 사용자가 다릅니다.')
        return json.loads(old['result'])


def save(user, identity, body):
    cid, parent_id = body['collectionId'], body['parentDocumentId']
    context(user, cid, parent_id, True)
    request_id = str(uuid.UUID(body['requestId']))
    mode = body.get('todayMode', 'next')
    if mode not in ('next', 'now'):
        raise ValueError('오늘 회차 처리 방식을 확인하세요.')
    settings = clean_settings(user, cid, body['settings'])
    fingerprint = hashlib.sha256(store.dump(body).encode()).hexdigest()
    at = schedule.now()
    rule_id = body.get('ruleId') or str(uuid.uuid5(uuid.NAMESPACE_URL, user['sub'] + ':recurring:' + request_id))
    with store.db() as c:
        c.execute('BEGIN IMMEDIATE')
        old_receipt = receipt(c, request_id, user, fingerprint)
        if old_receipt:
            return old_receipt
        previous = c.execute('SELECT * FROM recurring_rules WHERE id=?', (rule_id,)).fetchone()
        if previous:
            if (previous['collection_id'] != cid or previous['parent_id'] != parent_id
                    or not visible(user, previous)):
                raise HTTPException(404, '반복 업무를 찾을 수 없습니다.')
            if previous['revision'] != body.get('expectedRevision'):
                raise HTTPException(409, '다른 사용자가 설정을 변경했습니다. 새로고침 후 다시 확인하세요.')
            if c.execute('SELECT 1 FROM recurring_occurrences WHERE rule_id=? AND lease_until>?',
                         (rule_id, time.time())).fetchone():
                raise HTTPException(409, '회차가 처리 중입니다. 처리 완료 후 설정을 변경하세요.')
        elif body.get('ruleId'):
            raise HTTPException(404, '반복 업무를 찾을 수 없습니다.')
        elif date.fromisoformat(settings['startDate']) < at.date():
            raise ValueError('새 반복 업무의 반복 시작일은 오늘 이후로 지정하세요.')
        immediate = (not previous and mode == 'now' and schedule.matches(settings, at.date())
                     and at >= schedule.scheduled(at.date()))
        dates = schedule.preview(settings, at, include_today=immediate)
        if not dates and not previous:
            raise ValueError('생성할 반복 회차가 없습니다. 오늘 회차 지금 생성 또는 이후 반복 시작일을 선택하세요.')
        next_day = dates[0]['date'] if dates else ''
        if previous:
            # Today's settled occurrence must never be re-created after an edit.
            while next_day and c.execute('SELECT 1 FROM recurring_occurrences WHERE rule_id=? AND scheduled_date=?',
                                         (rule_id, next_day)).fetchone():
                following = schedule.next_date(settings, date.fromisoformat(next_day) + timedelta(days=1))
                next_day = following.isoformat() if following else ''
        revision = previous['revision'] + 1 if previous else 1
        state = previous['state'] if previous and previous['state'] in ('active', 'paused') else 'paused' if previous else 'active'
        if not next_day:
            state = 'completed'
        if previous:
            c.execute('UPDATE recurring_rules SET revision=?,state=?,body=?,next_date=?,updated_at=?,reason=? WHERE id=?',
                      (revision, state, store.dump(settings), next_day, store.now(), '', rule_id))
        else:
            c.execute('INSERT INTO recurring_rules VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                      (rule_id, cid, parent_id, user['sub'], user['sub'], identity['outlineUserId'], revision,
                       state, store.dump(settings), next_day, store.now(), store.now(), ''))
        c.execute('INSERT INTO recurring_versions VALUES(?,?,?,?,?)',
                  (rule_id, revision, store.dump(settings), user['sub'], store.now()))
        c.execute('INSERT INTO recurring_events(rule_id,actor,action,revision,at) VALUES(?,?,?,?,?)',
                  (rule_id, user['sub'], 'save', revision, store.now()))
        result = {'id': rule_id, 'revision': revision, 'immediate': immediate}
        c.execute('INSERT INTO recurring_requests VALUES(?,?,?,?,?)',
                  (request_id, user['sub'], fingerprint, store.dump(result), store.now()))
    if immediate:
        from . import recurring_worker
        recurring_worker.tick(rule_id=rule_id, immediate=True)
    return result


def change(user, identity, body, action):
    rule = get(user, body['collectionId'], body['parentDocumentId'], body['ruleId'], True)
    request_id = str(uuid.UUID(body['requestId']))
    fingerprint = hashlib.sha256(store.dump({'action': action, 'body': body}).encode()).hexdigest()
    with store.db() as c:
        c.execute('BEGIN IMMEDIATE')
        old = receipt(c, request_id, user, fingerprint)
        if old:
            return old
        current = c.execute('SELECT * FROM recurring_rules WHERE id=?', (rule['id'],)).fetchone()
        if current['revision'] != body.get('expectedRevision'):
            raise HTTPException(409, '반복 설정이 변경되었습니다. 새로고침 후 다시 확인하세요.')
        if current['state'] == 'archived':
            raise HTTPException(409, '종료된 반복 업무입니다.')
        state = {'pause': 'paused', 'resume': 'active', 'archive': 'archived', 'adopt': 'paused'}[action]
        if action == 'adopt' and not user.get('admin'):
            raise HTTPException(403, '업무 관리자만 실행 책임자를 인계할 수 있습니다.')
        if action == 'adopt' and c.execute('SELECT 1 FROM recurring_occurrences WHERE rule_id=? AND lease_until>?',
                                          (rule['id'], time.time())).fetchone():
            raise HTTPException(409, '처리 중인 회차가 끝난 뒤 실행 책임자를 인계하세요.')
        if action == 'resume' and current['state'] == 'needs_attention':
            raise HTTPException(409, '설정 또는 실행 책임자를 먼저 확인한 뒤 재개하세요.')
        dates = schedule.preview(json.loads(current['body'])) if action == 'resume' else None
        if dates is not None and not dates:
            raise HTTPException(409, '반복 일정이 종료되었습니다. 반복 시작일이나 반복 횟수를 수정하세요.')
        next_day = dates[0]['date'] if dates is not None else current['next_date']
        c.execute('UPDATE recurring_rules SET state=?,revision=revision+1,next_date=?,updated_at=?,reason=? WHERE id=?',
                  (state, next_day, store.now(), '', rule['id']))
        if action == 'adopt':
            c.execute('UPDATE recurring_rules SET executor_sub=?,outline_id=? WHERE id=?',
                      (user['sub'], identity['outlineUserId'], rule['id']))
            for pending in c.execute("SELECT id,snapshot,payload FROM recurring_occurrences WHERE rule_id=? "
                                     "AND status IN ('reserved','retry_wait','reconciling','needs_attention')", (rule['id'],)).fetchall():
                snapshot = json.loads(pending['snapshot'])
                snapshot.update(executor_sub=user['sub'], outline_id=identity['outlineUserId'])
                payload = json.loads(pending['payload']) if pending['payload'] else None
                if payload:
                    payload['executorId'] = identity['outlineUserId']
                c.execute('UPDATE recurring_occurrences SET snapshot=?,payload=? WHERE id=?',
                          (store.dump(snapshot), store.dump(payload) if payload else None, pending['id']))
        c.execute('INSERT INTO recurring_events(rule_id,actor,action,revision,at) VALUES(?,?,?,?,?)',
                  (rule['id'], user['sub'], action, current['revision'] + 1, store.now()))
        result = {'id': rule['id'], 'state': state}
        c.execute('INSERT INTO recurring_requests VALUES(?,?,?,?,?)',
                  (request_id, user['sub'], fingerprint, store.dump(result), store.now()))
    return result


def history(user, cid, parent_id, rule_id):
    rule = get(user, cid, parent_id, rule_id)
    with store.db() as c:
        rows = c.execute('SELECT id,scheduled_date,status,reason,attempts,result,created_at,updated_at '
                         'FROM recurring_occurrences WHERE rule_id=? ORDER BY scheduled_date DESC LIMIT 100',
                         (rule_id,)).fetchall()
    return {'rule': public(rule, user), 'occurrences': [
        {**dict(r), 'result': json.loads(r['result']) if r['result'] else None} for r in rows]}


def process_occurrence(user, body, action):
    rule = get(user, body['collectionId'], body['parentDocumentId'], body['ruleId'], True)
    request_id = str(uuid.UUID(body['requestId']))
    fingerprint = hashlib.sha256(store.dump({'action': action, 'body': body}).encode()).hexdigest()
    with store.db() as c:
        c.execute('BEGIN IMMEDIATE')
        old = receipt(c, request_id, user, fingerprint)
        if old:
            return old
        occurrence = c.execute('SELECT * FROM recurring_occurrences WHERE id=?', (body['occurrenceId'],)).fetchone()
        if not occurrence or occurrence['rule_id'] != rule['id']:
            raise HTTPException(404, '회차를 찾을 수 없습니다.')
        if occurrence['lease_until'] > time.time():
            raise HTTPException(409, '해당 회차가 처리 중입니다.')
        if occurrence['status'] not in ('missed', 'retry_wait', 'needs_attention', 'reconciling'):
            raise HTTPException(409, '이미 처리된 회차입니다. 새로고침 후 확인하세요.')
        if action == 'skip':
            # An uncertain write must be reconciled before it can be discarded.
            if occurrence['status'] != 'missed':
                raise HTTPException(409, '생성 결과를 먼저 확인하세요. 누락 회차만 건너뛸 수 있습니다.')
            c.execute("UPDATE recurring_occurrences SET status='skipped',reason=?,updated_at=? WHERE id=?",
                      ('사용자가 해당 회차를 건너뛰었습니다.', store.now(), occurrence['id']))
        else:
            c.execute("UPDATE recurring_occurrences SET status='reserved',retry_at=0,attempts=0 WHERE id=?",
                      (occurrence['id'],))
        c.execute('INSERT INTO recurring_events(rule_id,actor,action,revision,at) VALUES(?,?,?,?,?)',
                  (rule['id'], user['sub'], action + ':' + occurrence['scheduled_date'], rule['revision'], store.now()))
        result = {'id': occurrence['id']}
        c.execute('INSERT INTO recurring_requests VALUES(?,?,?,?,?)',
                  (request_id, user['sub'], fingerprint, store.dump(result), store.now()))
    if action != 'skip':
        from . import recurring_worker
        recurring_worker.execute(occurrence['id'])
    return {'id': occurrence['id']}
