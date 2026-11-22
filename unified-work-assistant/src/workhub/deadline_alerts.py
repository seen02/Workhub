"""Daily personal deadline digests, isolated from report jobs and chat menus."""
import hashlib
import logging
import os
import uuid
from collections import Counter
from datetime import datetime, date, timedelta
from urllib.parse import quote, urlsplit

from . import store, my_tasks, my_tasks_chat, chat_ui, report_transport

log = logging.getLogger('workhub.deadline_alerts')
HORIZON = 3
HOUR = 9
MINUTE = 0
WINDOW_MINUTES = 15
MAX_ATTEMPTS = 3
LEASE_SECONDS = 180
RETRY_SECONDS = 60
COMMANDS = {'알림': None, '알림 설정': None, '알림 받기': True,
            '알림 켜기': True, '알림 끄기': False}


def init():
    with store.db() as c:
        c.execute('''CREATE TABLE IF NOT EXISTS deadline_deliveries(
            subject TEXT NOT NULL, day TEXT NOT NULL, state TEXT NOT NULL,
            attempts INTEGER NOT NULL, next_attempt REAL NOT NULL,
            lease_until REAL NOT NULL, token TEXT NOT NULL,
            message_id TEXT NOT NULL, error_type TEXT NOT NULL DEFAULT '',
            updated TEXT NOT NULL, PRIMARY KEY(subject, day))''')


def enabled():
    return os.getenv('WORKHUB_DEADLINE_ALERTS_ENABLED', 'true').lower() == 'true'


def preference(user):
    return store.get('deadline-preference:' + user['sub'], {'enabled': True})


def route(user, uid, room, text):
    # Exact commands only; sentences about alerts must still reach reporting.
    if text not in COMMANDS:
        return None
    report_transport.require_dm(user, uid, room)
    value = COMMANDS[text]
    if value is not None:
        store.put('deadline-preference:' + user['sub'],
                  {'enabled': value, 'updated': store.now()})
    on = preference(user)['enabled']
    message = ('**마감 알림을 받고 있어요.**' if on else '**마감 알림을 껐어요.**')
    message += (f'\n매일 {HOUR:02d}:{MINUTE:02d}(한국 시간), 오늘부터 3일 이내 마감 업무와 기한 초과 업무를 '
                '이 개인 대화방으로 모아 보내드려요. 대상이 없으면 보내지 않아요.'
                if on else '\n다시 받으려면 `알림 받기`를 입력하세요.')
    if value is True:
        message += '\n예약된 마감 알림부터 적용됩니다.'
    actions = [chat_ui.button('알림 끄기' if on else '알림 받기',
                             '알림 끄기' if on else '알림 받기')]
    return message, chat_ui.attachment(actions, '마감 알림 설정', '#64748b')


def client():
    return report_transport.client()


def recipients():
    b = client()
    candidates = []
    for account in b.mongo.rocketchat.users.find(
            {'active': True}, {'services.authentik': 1, 'services.Authentik': 1}):
        if account['_id'] == b.bot_id:
            continue
        services = account.get('services', {})
        subjects = {str(binding[key]) for name in ('authentik', 'Authentik')
                    for binding in [services.get(name) or {}]
                    for key in ('id', 'sub') if binding.get(key)}
        if len(subjects) == 1:
            candidates.append((account['_id'], subjects.pop()))
    counts = Counter(sub for _, sub in candidates)
    # A duplicated SSO binding cannot select an arbitrary recipient.
    return [(uid, sub) for uid, sub in candidates if counts[sub] == 1]


def claim(subject, now):
    day = now.date().isoformat()
    stamp = now.timestamp()
    token = uuid.uuid4().hex
    mid = 'deadline-' + hashlib.sha256((subject + '\0' + day).encode()).hexdigest()[:40]
    with store.db() as c:
        c.execute('BEGIN IMMEDIATE')
        row = c.execute('SELECT * FROM deadline_deliveries WHERE subject=? AND day=?',
                        (subject, day)).fetchone()
        if row and (row['state'] in ('SENT', 'EMPTY', 'SKIPPED') or
                    row['attempts'] >= MAX_ATTEMPTS or row['lease_until'] > stamp or
                    row['next_attempt'] > stamp):
            return None
        attempts = row['attempts'] + 1 if row else 1
        c.execute('''INSERT INTO deadline_deliveries
            (subject,day,state,attempts,next_attempt,lease_until,token,message_id,error_type,updated)
            VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(subject,day) DO UPDATE SET
            state=excluded.state,attempts=excluded.attempts,lease_until=excluded.lease_until,
            token=excluded.token,updated=excluded.updated''',
                  (subject, day, 'SENDING', attempts, 0, stamp + LEASE_SECONDS,
                   token, mid, '', now.isoformat()))
    return {'subject': subject, 'day': day, 'token': token, 'message_id': mid}


def finish(job, state, now, error_type=''):
    with store.db() as c:
        c.execute('''UPDATE deadline_deliveries SET state=?,lease_until=0,
            next_attempt=?,error_type=?,updated=? WHERE subject=? AND day=? AND token=?''',
                  (state, now.timestamp() + RETRY_SECONDS if state == 'RETRY' else 0,
                   error_type, now.isoformat(), job['subject'], job['day'], job['token']))


def due_rows(data, today):
    if not data.get('complete'):
        raise ValueError('IncompleteInventory')
    return [row for row in data['rows'] if row['fields'].get('status') != '완료'
            and row['fields'].get('due') not in (None, '', '미정')
            and date.fromisoformat(row['fields']['due']) <= today + timedelta(days=HORIZON)]


def source_link(row):
    url = row.get('url', '')
    parts = urlsplit(url)
    if parts.scheme not in ('http', 'https') or not parts.netloc:
        return ''
    return '[문서로 이동](' + quote(url, safe=':/?=&%#') + ')'


def render(rows, today, example=False):
    counts = Counter('overdue' if date.fromisoformat(row['fields']['due']) < today
                     else 'today' if row['fields']['due'] == today.isoformat()
                     else 'upcoming' for row in rows)
    heading = '마감 알림 예시' if example else '마감 알림'
    lines = [f'**{heading} · {today.month}월 {today.day}일 기준**',
             f'확인할 업무 **{len(rows)}건**',
             f"기한 초과 {counts['overdue']} · 오늘 마감 {counts['today']} · 3일 이내 {counts['upcoming']}"]
    if example:
        lines.append('표시 방식 확인용 예시입니다.')
    labels = {**my_tasks.LABELS, 'upcoming': '🔵 3일 이내 마감'}
    def group(row):
        due = date.fromisoformat(row['fields']['due'])
        return 'overdue' if due < today else 'today' if due == today else 'upcoming'
    ordered = sorted(rows, key=lambda row: (my_tasks.GROUPS.index(group(row)),
                     row['fields']['due'], row['collectionName'], row['title'], row['id']))
    shown = 0
    last_group = None
    for row in ordered[:my_tasks_chat.PAGE_SIZE]:
        due = date.fromisoformat(row['fields']['due'])
        current_group = group(row)
        view = {**row, 'group': current_group, 'late_days': max(0, (today - due).days)}
        remaining = row.get('remaining', [])
        block = f"\n**{labels[current_group]} · {counts[current_group]}건**\n" if current_group != last_group else ''
        block += (f"\n**{shown + 1}. [{my_tasks_chat.clean(row['collectionName'], 60)}] {my_tasks_chat.clean(row['title'], 100)}**\n"
                  f"{my_tasks_chat.deadline(view)} · {my_tasks_chat.clean(row['fields']['status'])}")
        mine = row.get('mine', remaining)
        if mine:
            block += f'\n내 완료 기준: {len(mine) - len(remaining)}/{len(mine)} 완료'
            for criterion in remaining[:3]:
                block += f"\n• {my_tasks_chat.clean(criterion['title'], 110)} — {my_tasks_chat.clean(criterion['state'])}"
            if len(remaining) > 3:
                block += f'\n남은 기준 {len(remaining) - 3}개 더 있음 · `내 업무`에서 확인'
        else:
            block += '\n완료 기준 미등록'
        link = source_link(row)
        if link:
            block += '\n' + link
        if sum(len(line) + 1 for line in lines) + len(block) > 8400:
            break
        lines.append(block)
        shown += 1
        last_group = current_group
    if shown < len(rows):
        lines.append(f'\n이외 {len(rows) - shown}건은 `내 업무`로 확인하세요.')
    lines.append('\n전체 업무는 `내 업무`로 확인하세요.')
    lines.append(f'매일 {HOUR:02d}:{MINUTE:02d}(한국 시간) 알림 · 받기/끄기는 `알림`')
    return '\n'.join(lines)


def attachments():
    # Fixed commands do not bind buttons, replace numbered menus or edit drafts.
    return [{'color': '#cbd5e1', 'actions': [chat_ui.button(label, command)]}
            for label, command in [('내 업무 전체 보기', '내 업무'), ('알림 설정', '알림')]]


def dm(user, uid):
    b = client()
    room = b.mongo.rocketchat.rocketchat_room.find_one(
        {'t': 'd', 'uids': {'$all': [uid, b.bot_id], '$size': 2}})
    if not room:
        account = b.mongo.rocketchat.users.find_one({'_id': uid, 'active': True}, {'username': 1})
        if not account or not account.get('username'):
            raise ValueError('InactiveRecipient')
        result = b.api('dm.create', {'username': account['username']})
        if result.get('success') is not True:
            raise ValueError('DMCreationFailed')
        rid = result.get('room', {}).get('rid')
    else:
        rid = room['_id']
    report_transport.require_dm(user, uid, rid)
    room = b.mongo.rocketchat.rocketchat_room.find_one({'_id': rid})
    if not room or room.get('archived') or room.get('encrypted') or room.get('blocked'):
        raise ValueError('UnavailableDM')
    return rid


def deliver(uid, subject, now):
    b = client()
    if not preference({'sub': subject})['enabled']:
        return 'SKIPPED'
    job = claim(subject, now)
    if job is None:
        return 'ALREADY_CHECKED'
    try:
        user = b.identity(uid)
        if user['sub'] != subject:
            raise ValueError('RecipientChanged')
        existing = report_transport.lookup(job['message_id'])
        if existing:
            report_transport.require_dm(user, uid, existing['rid'])
            if existing.get('u', {}).get('_id') != b.bot_id:
                raise ValueError('MessageIdentityMismatch')
            finish(job, 'SENT', now)
            return 'SENT'
        rows = due_rows(my_tasks.collect(user, now), now.date())
        if not rows:
            finish(job, 'EMPTY', now)
            return 'EMPTY'
        rid = dm(user, uid)
        # Refresh authorization and inventory immediately before the side effect.
        current = b.identity(uid)
        if current['sub'] != subject or current['email'] != user['email']:
            raise ValueError('RecipientChanged')
        rows = due_rows(my_tasks.collect(current, now), now.date())
        if not preference(current)['enabled']:
            finish(job, 'SKIPPED', now)
            return 'SKIPPED'
        if not rows:
            finish(job, 'EMPTY', now)
            return 'EMPTY'
        report_transport.require_dm(current, uid, rid)
        result = b.api('chat.sendMessage', {'message': {
            '_id': job['message_id'], 'rid': rid, 'msg': render(rows, now.date()),
            'attachments': attachments()}, 'previewUrls': []})
        if result.get('success') is not True:
            raise ValueError('MessageSendFailed')
        finish(job, 'SENT', now)
        return 'SENT'
    except Exception as ex:
        finish(job, 'RETRY', now, type(ex).__name__)
        log.warning('deadline_delivery_pending type=%s', type(ex).__name__)
        return 'RETRY'


def tick(now=None):
    now = (now or datetime.now(my_tasks.KST)).astimezone(my_tasks.KST)
    scheduled = now.replace(hour=HOUR, minute=MINUTE, second=0, microsecond=0)
    if not enabled() or not scheduled <= now < scheduled + timedelta(minutes=WINDOW_MINUTES):
        return {}
    b = client()
    if not b.bot_id or not b.headers:
        return {}
    outcomes = Counter()
    for uid, subject in recipients():
        try:
            outcomes[deliver(uid, subject, now)] += 1
        except Exception as ex:
            outcomes['UNAVAILABLE'] += 1
            log.warning('deadline_recipient_unavailable type=%s', type(ex).__name__)
    store.put('deadline-alerts-status', {'at': now.isoformat(), 'outcomes': dict(outcomes)})
    return dict(outcomes)


def run(stop):
    # Own thread: no report queue, per-user report lock, LLM or menu/session writes.
    while not stop.is_set():
        try:
            tick()
        except Exception as ex:
            log.warning('deadline_scheduler_pending type=%s', type(ex).__name__)
        stop.wait(30)
