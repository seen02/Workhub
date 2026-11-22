"""User-requested preview to one existing SSO DM, using synthetic tasks only."""
import argparse
import hashlib
import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from pymongo import MongoClient
from workhub import bot, store, outline, permissions, my_tasks, deadline_alerts as alerts

parser = argparse.ArgumentParser()
parser.add_argument('--email', required=True)
parser.add_argument('--update', action='store_true', help='Update the same bot-owned preview after an explicitly requested change')
args = parser.parse_args()
email = args.email.strip().lower()


def snapshot():
    with store.db() as c:
        values = [tuple(row) for row in c.execute('SELECT id,body,state FROM proposals ORDER BY id')]
        values += [tuple(row) for row in c.execute('''SELECT k,v FROM kv WHERE
            k LIKE 'report-v2:%' OR k LIKE 'chat-context:%' OR k LIKE 'chat-menu:%'
            OR k LIKE 'chat-choice:%' OR k LIKE 'my-tasks-session:%' ORDER BY k''')]
        values += [tuple(row) for row in c.execute('SELECT * FROM deadline_deliveries ORDER BY subject,day')]
    return hashlib.sha256(store.dump(values).encode()).hexdigest()


before = snapshot()
with store.db() as c:
    bindings = c.execute('SELECT sub FROM identities WHERE lower(email)=?', (email,)).fetchall()
assert len(bindings) == 1, 'A unique existing Workhub SSO identity is required'
subject = bindings[0]['sub']
bot.mongo = MongoClient(os.environ['MONGO_URL'], serverSelectionTimeoutMS=5000)
candidates = list(bot.mongo.rocketchat.users.find({'active': True, '$or': [
    {'services.' + service + '.' + key: subject}
    for service in ('authentik', 'Authentik') for key in ('id', 'sub')]}, {'_id': 1}))
assert len(candidates) == 1, 'A unique active Rocket.Chat SSO binding is required'
uid = candidates[0]['_id']
login = bot.api('login', {'user': os.environ['BOT_USERNAME'], 'password': os.environ['BOT_PASSWORD']})['data']
bot.bot_id = login['userId']
bot.headers = {'X-User-Id': bot.bot_id, 'X-Auth-Token': login['authToken']}
user = bot.identity(uid)
assert user['sub'] == subject and user['email'].lower() == email
rid = alerts.dm(user, uid)
fixture = json.loads(Path('/app/data/my-tasks-demo.json').read_text())
assert fixture['actor'].lower() == email and fixture['uid'] == uid and fixture['dm'] == rid
links = {}
for code, key in [('late', 'overdue'), ('today', 'today'), ('soon', 'upcoming')]:
    doc = outline.api('documents.info', {'id': fixture['tasks'][key]['id']})
    permissions.project(user, doc['collectionId'])
    assert doc.get('publishedAt') and not doc.get('deletedAt') and not doc.get('archivedAt')
    url = doc.get('url', '')
    links[code] = outline.PUBLIC + url if url.startswith('/') else url
    assert alerts.source_link({'url': links[code]})
now = datetime.now(my_tasks.KST)
rows = []
specs = [('late', '예시 서비스 프로젝트', '로그인 화면 수정', -2,
          [('화면 배치 수정', '완료'), ('오류 안내 문구 적용', '진행 중'), ('모바일 화면 확인', '예정')]),
         ('today', '예시 운영 프로젝트', '운영 안내서 정리', 0,
          [('안내서 초안 작성', '완료'), ('내용 검토 및 공유', '진행 중')]),
         ('soon', '예시 서비스 프로젝트', '검색 결과 개선', 2,
          [('검색 결과 표시 구현', '진행 중'), ('사용자 시나리오 점검', '예정')])]
for code, project, title, days, criteria in specs:
    task = {'id': 'example-' + code, 'collectionName': project, 'title': title, 'url': links[code],
            'fields': {'owner': email, 'status': '진행 중',
                       'due': (now.date() + timedelta(days=days)).isoformat()},
            'criteria': [{'id': code + str(n), 'title': label, 'state': state, 'owner': email}
                         for n, (label, state) in enumerate(criteria)]}
    rows.append(my_tasks.personal(task, user, now.date()))
text = alerts.render(rows, now.date(), example=True)
mid = 'deadline-example-readable-20261012-' + hashlib.sha256(subject.encode()).hexdigest()[:24]
existing = bot.mongo.rocketchat.rocketchat_message.find_one({'_id': mid})
if existing:
    assert existing['rid'] == rid and existing['u']['_id'] == bot.bot_id
    if existing['msg'] != text:
        assert args.update, 'Explicit update requested for this preview is required'
        result = bot.api('chat.update', {'roomId': rid, 'msgId': mid, 'text': text, 'previewUrls': []})
        assert result.get('success') is True
else:
    result = bot.api('chat.sendMessage', {'message': {
        '_id': mid, 'rid': rid, 'msg': text, 'attachments': alerts.attachments()}, 'previewUrls': []})
    assert result.get('success') is True
message = bot.mongo.rocketchat.rocketchat_message.find_one({'_id': mid})
assert message and message['rid'] == rid and message['msg'] == text and message['u']['_id'] == bot.bot_id
assert message['msg'].count('[문서로 이동](') == 3
assert snapshot() == before, 'A preview must preserve drafts, menus and daily delivery history'
bot.mongo.close()
print(json.dumps({'passed': True, 'at': store.now(), 'recipient': email,
    'example_sent': True, 'synthetic_tasks': True, 'document_links': 3,
    'example_updated': bool(existing and args.update), 'report_and_schedule_state_preserved': True,
    'schedule_kst': f'{alerts.HOUR:02d}:{alerts.MINUTE:02d}', 'example_text': text}, ensure_ascii=False))
