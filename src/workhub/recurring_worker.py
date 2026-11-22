"""Bounded background generation with fixed document identities and live principals."""
import hashlib
import hmac
import json
import logging
import os
import time
import uuid
from datetime import date, timedelta
from fastapi import HTTPException
from . import domain, http_pool, outline, outline_bridge, permissions, store, task_creation
from . import recurring_schedule as schedule, recurring_store as records

LOG = logging.getLogger('workhub.recurring')


def payload_for(rule, occurrence, user):
    body = json.loads(rule['body'])
    from .recurring_service import clean_settings
    body = clean_settings(user, rule['collection_id'], body)
    people = {p['id']: p for p in permissions.assignees(user, rule['collection_id'])}
    label = lambda person: person['name'] + ' (' + person['email'] + ')'
    owner = people[body['ownerId']]
    day = occurrence['scheduled_date']
    dates = schedule.task_dates(body, date.fromisoformat(day))
    start, due = dates['startDate'] or '미정', dates['dueDate'] or '미정'
    items = '\n'.join('- [ ] ' + task_creation.escape(i['title']) + ' — 담당자: '
                      + label(people[i['assigneeId']]) for i in body['criteria'])
    text = (f"담당자: {label(owner)}\n\n시작일: {start}\n\n마감일: {due}\n\n"
            '상태: 미착수\n\n진행률: 0%\n\n결과물: 없음\n\n## 업무 내용\n\n'
            + task_creation.escape(body['notes']) + '\n\n## 완료 기준\n\n' + items
            + '\n\n## 반복 업무 정보\n\n반복 규칙 ID: ' + rule['id']
            + '\n\n회차 날짜: ' + day + '\n\n자동 생성 예정: ' + day + ' 07:00 (한국 시간)')
    domain.parse(text)
    return {'executorId': rule['outline_id'], 'teamId': os.getenv('OUTLINE_WORKHUB_TEAM_ID', ''),
            'collectionId': rule['collection_id'], 'parentDocumentId': rule['parent_id'],
            'documentId': occurrence['document_id'], 'occurrenceId': occurrence['id'],
            'ruleId': rule['id'], 'date': day, 'title': body['title'] + ' · ' + day, 'text': text}


def native_request(payload):
    path = '/api/workhub.recurringExecute'
    raw = json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    stamp, nonce = str(int(time.time())), str(uuid.uuid4())
    message = '\n'.join(['POST', path, stamp, nonce, hashlib.sha256(raw).hexdigest()])
    secret = os.getenv('OUTLINE_WORKHUB_BRIDGE_SECRET', '')
    if not secret:
        raise HTTPException(503, 'Outline 연동 설정을 확인하세요.')
    headers = {**outline.HEADERS, 'Content-Type': 'application/json', 'X-Workhub-Time': stamp,
               'X-Workhub-Nonce': nonce,
               'X-Workhub-Signature': hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()}
    response = http_pool.request('outline', 'POST', outline.URL + path, metric='recurring.execute',
                                 content=raw, headers=headers, timeout=60)
    if not response.is_success:
        code = response.status_code
        if code == 400:
            raise HTTPException(422, 'Outline이 업무 생성 값을 거부했습니다. 반복 업무 설정을 확인한 뒤 다시 시도하세요.')
        raise HTTPException(code if code in (401, 403, 404, 409, 422) else 503,
                            '현재 계정·업무 목록·생성 권한을 확인하세요.' if code in (401, 403, 404, 409, 422)
                            else 'Outline 생성 결과를 확인 중입니다. 같은 회차로 재확인합니다.')
    result = response.json().get('data')
    if not isinstance(result, dict) or result.get('id') != payload['documentId']:
        raise HTTPException(503, '예약된 문서의 생성 결과를 확인하지 못했습니다.')
    return result


def execute(occurrence_id):
    lease = records.claim(occurrence_id)
    if not lease:
        return
    occurrence = records.occurrence(occurrence_id)
    rule = json.loads(occurrence['snapshot'])
    token = permissions.request_snapshots.set({})
    try:
        user = outline_bridge.actor({'outlineUserId': rule['outline_id'],
                                      'outlineTeamId': os.getenv('OUTLINE_WORKHUB_TEAM_ID', '')})
        if user['sub'] != rule['executor_sub']:
            raise HTTPException(403, '반복 업무 실행 계정 연결을 확인하세요.')
        task_creation.context(user, rule['collection_id'], rule['parent_id'])
        # Revalidate every assignee even when retrying a frozen document payload.
        from .recurring_service import clean_settings
        settings = clean_settings(user, rule['collection_id'], json.loads(rule['body']))
        occurrence = records.prepare_document_id(occurrence_id, lease)
        if settings['unfinishedPolicy'] == 'skip' and not occurrence['payload']:
            with store.db() as c:
                previous = c.execute("SELECT document_id FROM recurring_occurrences WHERE rule_id=? "
                                     "AND scheduled_date<? AND status='created' ORDER BY scheduled_date DESC",
                                     (rule['id'], occurrence['scheduled_date'])).fetchall()
            for row in previous:
                document = outline.document(row['document_id'])
                if (document.get('archivedAt') or document.get('deletedAt') or
                        document.get('collectionId') != rule['collection_id']):
                    raise HTTPException(409, '이전 회차의 위치나 상태를 확인하세요.')
                fields = domain.parse(document.get('text', ''))
                if not fields:
                    raise HTTPException(409, '이전 회차의 업무 양식을 확인하세요.')
                if fields['status'] != '완료':
                    records.finish(occurrence_id, lease, 'skipped', reason='이전 회차 미완료로 건너뛰었습니다.')
                    return
        payload = json.loads(occurrence['payload']) if occurrence['payload'] else payload_for(rule, occurrence, user)
        payload = records.freeze_payload(occurrence_id, lease, payload)
        result = native_request(payload)
        document = outline.document(result['id'])
        task = outline.record(document, user['email'], 'recurring-created')
        if not task or task.get('error'):
            raise HTTPException(503, '문서는 생성되었으며 업무 목록 반영을 다시 확인합니다.')
        records.finish(occurrence_id, lease, 'created', result=result)
        LOG.info('occurrence_created id=%s', occurrence_id)
    except Exception as error:
        terminal = isinstance(error, HTTPException) and error.status_code in (401, 403, 404, 409, 422)
        exhausted = occurrence['attempts'] >= 5
        reason = (str(error.detail) if isinstance(error, HTTPException) else '연결 오류로 생성 결과를 다시 확인합니다.')[:400]
        status = 'needs_attention' if terminal or exhausted else 'reconciling'
        records.finish(occurrence_id, lease, status, reason=reason,
                       retry_at=time.time() + [60, 300, 900, 1800, 3600][min(occurrence['attempts'] - 1, 4)])
        if terminal or exhausted:
            with store.db() as c:
                c.execute("UPDATE recurring_rules SET state='needs_attention',reason=?,revision=revision+1,updated_at=? "
                          "WHERE id=? AND state IN ('active','completed')", (reason, store.now(), rule['id']))
        LOG.warning('occurrence_pending id=%s type=%s', occurrence_id, type(error).__name__)
    finally:
        permissions.request_snapshots.reset(token)
        records.complete_if_finished(rule['id'])


def tick(*, rule_id=None, immediate=False, at=None):
    from .recurring_service import enabled
    if not enabled():
        return
    at = at or schedule.now()
    if not immediate and at < schedule.scheduled(at.date()):
        return
    with store.db() as c:
        rows = c.execute("SELECT id FROM recurring_rules WHERE state='active' AND next_date<>'' AND next_date<=?"
                         + (' AND id=?' if rule_id else '') + ' ORDER BY next_date LIMIT 10',
                         (at.date().isoformat(), rule_id) if rule_id else (at.date().isoformat(),)).fetchall()
    for row in rows:
        # One transaction serializes pause/save versus reserving the immutable run.
        for _ in range(100):
            with store.db() as c:
                c.execute('BEGIN IMMEDIATE')
                rule = c.execute("SELECT * FROM recurring_rules WHERE id=? AND state='active'", (row['id'],)).fetchone()
                if not rule or not rule['next_date'] or rule['next_date'] > at.date().isoformat():
                    break
                rule = dict(rule)
                day = rule['next_date']
                settings = json.loads(rule['body'])
                last = schedule.end_date(settings)
                if last and date.fromisoformat(day) > last:
                    c.execute("UPDATE recurring_rules SET next_date='',state='completed',updated_at=? WHERE id=?",
                              (store.now(), rule['id']))
                    break
                missed = day < at.date().isoformat()
                occurrence_id = records.reserve_in(c, rule, day, 'missed' if missed else 'reserved',
                                                   '서버 중단 등으로 생성일이 지났습니다.' if missed else '')
                following = schedule.next_date(settings, date.fromisoformat(day) + timedelta(days=1))
                next_day = following.isoformat() if following else ''
                c.execute('UPDATE recurring_rules SET next_date=?,updated_at=? WHERE id=?', (next_day, store.now(), rule['id']))
            if not missed:
                execute(occurrence_id)
                break
        records.complete_if_finished(row['id'])
    with store.db() as c:
        pending = c.execute("SELECT o.id FROM recurring_occurrences o JOIN recurring_rules r ON r.id=o.rule_id "
                            "WHERE o.status IN ('reserved','creating','retry_wait','reconciling') "
                            "AND o.retry_at<=? AND o.lease_until<=? ORDER BY o.scheduled_date LIMIT 10",
                            (time.time(), time.time())).fetchall()
    for row in pending:
        execute(row['id'])


def run(stop):
    while not stop.is_set():
        try:
            tick()
        except Exception as error:
            LOG.warning('scheduler_pending type=%s', type(error).__name__)
        stop.wait(30)
