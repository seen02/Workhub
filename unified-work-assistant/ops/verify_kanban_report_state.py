"""Submit a real Rocket.Chat report for an explicitly created test task only."""
import json, os, sys, uuid
from pathlib import Path
from pymongo import MongoClient
from fastapi import HTTPException
sys.path.insert(0,'/app')
from workhub import auth, bot, store, outline, criteria, reports, provision, domain

fixture=json.loads(Path(sys.argv[1]).read_text())
assert fixture['title'].startswith('[검증] 칸반 기준 ')
doc=outline.api('documents.info',{'id':fixture['taskId']})
assert doc['title']==fixture['title'] and doc['parentDocumentId']==fixture['parentId']
if fixture.get('markerDeleted'):assert '상태 관리: 칸반' not in domain.source_text(doc['text'])
with store.db() as c:sub=c.execute('SELECT sub FROM identities WHERE email=?',(fixture['email'],)).fetchone()['sub']
user=auth.for_subject(sub)
bot.mongo=MongoClient(os.environ['MONGO_URL'])
login=bot.api('login',{'user':os.environ['BOT_USERNAME'],'password':os.environ['BOT_PASSWORD']})['data']
bot.bot_id=login['userId'];bot.headers={'X-User-Id':bot.bot_id,'X-Auth-Token':login['authToken']}
actor=bot.mongo.rocketchat.users.find_one({'emails.address':user['email']})
dm=bot.api('im.create',{'username':actor['username']})['room']['rid']
items=criteria.parse(doc['text']);own=next(i for i in items if i['owner']==user['email'])
other=next(i for i in items if i['owner']!=user['email'])
try:outline.authorize_changes(user,doc,{'criterion_states':{other['id']:'완료'}})
except HTTPException as error:assert error.status_code==403
else:raise AssertionError('Reporting another owner criterion was allowed')
rid='kanban-state-test-'+uuid.uuid4().hex;room=None
previous=store.get('report-destination:'+sub)
try:
    room=provision.call('groups.create',{'name':'kanban-state-test-'+uuid.uuid4().hex[:12],
        'members':[actor['username'],os.environ['BOT_USERNAME']]})['group']['_id']
    group={'kind':'update','state':'PENDING','task_id':doc['id'],'project_id':doc['collectionId'],
        'project_name':outline.project(doc['collectionId'])['name'],'title':doc['title'],
        'before':doc['text'],'revision':doc['revision'],'updatedAt':doc['updatedAt'],
        'evidence':own['title']+' 완료했습니다.','items':[{'id':own['id'],'title':own['title'],'state':'완료'}]}
    reports.save({'id':rid,'version':1,'owner':sub,'author':user['email'],'uid':actor['_id'],'dm':dm,
        'when':store.now(),'raw':group['evidence'],'groups':[group],
        'posting':{'state':'NOT_POSTED'},'destination':None})
    result=reports.submit(user,rid,1,room)
    assert result['posting']['state']=='POSTED',result['posting']['state']
    assert result['groups'][0]['state']=='APPLIED',result['groups'][0].get('error')
    current=outline.document(doc['id'],user)
    fields=outline.projected(current)['fields'];updated=criteria.parse(current['text'])
    assert fields['status']=='보류' and fields['progress']=='50%'
    assert next(i for i in updated if i['id']==own['id'])['state']=='완료'
    assert next(i for i in updated if i['id']==other['id'])==other
    message=bot.mongo.rocketchat.rocketchat_message.find_one({'_id':result['posting']['message_id'],'rid':room})
    assert message and own['title']+'(✅ 완료)' in message['msg']
    assert '보고 ID: '+rid in current['text']
    print(json.dumps({'successful':True,'rocketChatPosted':True,'outlineApplied':True,
        'manualStatusPreserved':True,'unmentionedCriterionPreserved':True,
        'otherCriterionReportDenied':True,'progress':50},ensure_ascii=False))
finally:
    if room:provision.call('groups.delete',{'roomId':room})
    store.put('report-destination:'+sub,previous)
    with store.db() as c:
        c.execute('DELETE FROM kv WHERE k=?',('report-v2:'+rid,))
        c.execute('DELETE FROM proposals WHERE owner=? AND idem LIKE ?',(sub,'report-v2:'+rid+':%'))
