"""Reuse the original reconnecting Rocket.Chat DDP stream; write through Outline proposals."""
import json, logging, os, queue, threading, time, re
from urllib.parse import quote
from datetime import datetime, timezone, timedelta
import httpx
from pymongo import MongoClient
from legacy_app.rocketchat.realtime import RoomMessageStream
from . import auth, outline, assistant, store, domain, criteria, directory, chat_ui, permissions
from . import report_chat, execution, http_pool, my_tasks_chat, job_control, knowledge_chat
from . import deadline_alerts

log=logging.getLogger('workhub.bot')
URL=os.getenv('ROCKETCHAT_INTERNAL_URL','http://rocketchat:3000')
JOBS=queue.Queue(maxsize=50)
CONTROLS=queue.Queue(maxsize=50)
headers={};bot_id=None;stream=None
mongo=None

def api(path,body=None):
    for attempt in range(3):
        r=http_pool.request('rocketchat','POST' if body is not None else 'GET',URL+'/api/v1/'+path,metric=path.split('?')[0],json=body,headers=headers,timeout=20)
        if r.status_code==429:time.sleep(min(10,2**attempt));continue
        r.raise_for_status();return r.json()
    raise RuntimeError('Rocket.Chat 요청 제한')

@execution.measured('chat_notice')
def say(room,text,attachments=None):
    # Long multi-task previews must not silently lose their trailing results.
    remaining=text
    while len(remaining)>9500:
        cut=remaining.rfind('\n',0,9500)+1 or 9500
        api('chat.postMessage',{'roomId':room,'text':remaining[:cut]})
        remaining=remaining[cut:]
    return api('chat.postMessage',{'roomId':room,'text':remaining,**({'attachments':attachments} if attachments else {})})

def identity(uid):
    # Match signed OIDC subject stored by Rocket.Chat, never a user-editable display name/email.
    u=mongo.rocketchat.users.find_one({'_id':uid},{'services.authentik':1,'services.Authentik':1,'active':1})
    if not u or u.get('active') is not True:raise ValueError('활성 SSO 계정이 아닙니다.')
    bindings=[u.get('services',{}).get(name) or {} for name in ('authentik','Authentik')]
    subjects={str(s[key]) for s in bindings for key in ('id','sub') if s.get(key)}
    if len(subjects)!=1:raise ValueError('Authentik으로 로그인한 계정의 SSO 연결을 확인하세요.')
    return auth.for_subject(subjects.pop())

HELP='**통합 업무 비서**\nRocket.Chat에 Authentik으로 로그인한 계정으로 이용하세요. 별도 포털 로그인은 필요하지 않습니다.\n① `시작`을 입력한 뒤 프로젝트 이름 → 업무 이름 버튼을 누릅니다.\n② 진행 상황을 편하게 입력합니다.\n③ 기존 양식의 초안을 확인하고 **이 보고 확정** 버튼을 누릅니다.\n`프로젝트` — 프로젝트 변경\n`업무` — 보고할 업무 다시 선택\n`현재 업무` — 선택한 업무와 완료 기준\n`취소` — 현재 업무의 최근 채팅 초안 취소 (또는 이 초안 취소 버튼)\n`작성 <업무명> | <메모>` — 선택한 프로젝트에 내 업무 등록\n`자료 <질문>` — 선택한 프로젝트 자료 검색\n`주간보고` — 관리자 현황 초안\n완료 기준 작성·담당자 분배는 Outline에서 관리자가 합니다.'

def preview(p):
    fields=domain.parse(p['after'])
    return p.get('formatted_report',f"**{p['title']} 변경 제안**")+f"\n\n업무 전체: {fields['status']} · {fields['progress']}\n근거: {p.get('evidence','사용자 입력')}\n아직 Outline에 반영되지 않았습니다. **이 보고 확정** 또는 **이 초안 취소**를 누르세요."

def remember_draft(context_key,context,p):
    context.update(taskId=p['doc_id'],collectionId=p['collectionId'],proposalId=p['id'])
    store.put(context_key,context)

def latest_chat_draft(user,room,context):
    if context.get('proposalId'):
        p=outline.proposal(user,context['proposalId'])
        if p['doc_id']==context.get('taskId'):return p['id']
    # Compatibility for drafts sent before cancellation was introduced. Never
    # select a portal draft, another DM, or an older draft just because the newest
    # one is already applied/cancelled.
    with store.db() as c:
        rows=c.execute('SELECT p.id,p.body,m.body AS message FROM proposals p JOIN messages m ON p.idem=?||m.id WHERE p.owner=? ORDER BY p.created DESC',('rc:',user['sub'])).fetchall()
    for row in rows:
        if json.loads(row['message']).get('rid')==room and json.loads(row['body'])['doc_id']==context.get('taskId'):return row['id']
    raise ValueError('현재 업무의 이 대화에서 취소할 초안이 없습니다. 초안의 이 초안 취소 버튼을 이용하세요.')

def prepare_report(user,uid,room,context_key,context,text,mid,received):
    report_chat.report_transport.require_dm(user,uid,room)
    with job_control.running(uid,room,received) as job:
        stamp=datetime.now(timezone(timedelta(hours=9))).strftime('%m/%d %H:%M:%S')
        stop=chat_ui.bind(context_key,'⏹ 긴급 취소','긴급 취소 · '+stamp,{'kind':'job-cancel','id':job.id})
        stop['text']='⏹ 긴급 취소'
        job.command=stop['msg']
        say(room,'보고문을 정리하고 있어요. 멈추려면 **긴급 취소**를 누르거나 `중단`을 입력하세요.',
            [{'color':'#dc2626','actions':[stop]}])
        result=report_chat.draft(user,uid,room,context_key,context,text,mid)
        job_control.check()
        return result


def handle(m):
    uid=m.get('u',{}).get('_id');mid=m.get('_id');room=m.get('rid');text=m.get('msg','').strip()
    if not uid or uid==bot_id or not mid or m.get('t') or not text:return
    with store.db() as c:
        old=c.execute('SELECT state FROM messages WHERE id=?',(mid,)).fetchone()
        if old:return
        c.execute('INSERT INTO messages VALUES(?,?,?)',(mid,'PROCESSING',store.dump(m)))
        if job_control.discarded(uid,room,m.get('_workhub_received_at')):
            c.execute('UPDATE messages SET state=? WHERE id=?',('CANCELLED',mid))
            return
    try:
        user=identity(uid)
        context_key='chat-context:'+user['sub']+':'+room
        context=store.get(context_key,{})
        cid=context.get('collectionId','')
        attachments=None
        text=chat_ui.numbered(context_key,text)
        choice=chat_ui.resolve(context_key,text)
        if text in ('업무 계획','업무계획','내 업무 계획','할 일','할일'):text='내 업무'
        routed=deadline_alerts.route(user,uid,room,text)
        if routed is None:routed=my_tasks_chat.route(user,uid,room,context_key,context,text,choice)
        if routed is None:routed=report_chat.route(user,uid,room,context_key,context,text,choice)
        if routed is not None:
            say(room,*routed)
            with store.db() as c:c.execute('UPDATE messages SET state=? WHERE id=?',('DONE',mid))
            return
        if choice:
            if choice['kind']=='project':text='프로젝트 '+choice['id']
            elif choice['kind']=='task':
                # The clicked card owns its project context, even if a newer
                # menu is open. Never resolve a title against the wrong project.
                cid=permissions.project(user,choice['collectionId'])['id']
                text='업무선택 '+choice['id']
            elif choice['kind']=='confirm':
                if choice['taskId']!=context.get('taskId'):raise ValueError('이 초안의 업무를 다시 선택한 후 확정하세요. 현재 선택한 업무와 다릅니다.')
                text='확정 '+choice['id']
            elif choice['kind']=='cancel':text='취소 '+choice['id']
        elif text.startswith(('프로젝트 선택 ·','업무 선택 ·','보고 확정 ·','보고 취소 ·')):
            raise ValueError('이 대화에서 제공한 선택 버튼이 아닙니다. 프로젝트를 입력해 새 목록을 여세요.')
        page_match=re.fullmatch(r'(프로젝트|업무) 목록 ([1-9][0-9]*)쪽',text)
        if text in ('취소','보고 취소','초안 취소') or text.startswith('취소 '):
            pid=text.split(maxsplit=1)[1] if text.startswith('취소 ') else latest_chat_draft(user,room,context)
            p=outline.cancel(user,pid)
            if p['doc_id']==context.get('taskId') and not context.get('proposalId'):
                context['proposalId']=p['id'];store.put(context_key,context)
            answer=f"초안 취소 완료: {p['title']}\nOutline 원본·완료 체크·진행률은 변경하지 않았습니다.\n새 보고를 입력하면 새 초안을 만들 수 있습니다."
            attachments=chat_ui.navigation()
        elif text in ('도움말','help'):
            answer=report_chat.INTRO
        elif text in ('시연','시작','메뉴','프로젝트','프로젝트 변경') or (page_match and page_match[1]=='프로젝트'):
            answer,attachments=chat_ui.projects(context_key,user,int(page_match[2]) if page_match else 1)
        elif text.startswith('프로젝트 '):
            p=permissions.project(user,text.split(maxsplit=1)[1]);context={'collectionId':p['id']};store.put(context_key,context)
            outline.sync();answer,attachments=chat_ui.tasks(context_key,user,p['id'])
            answer=f"선택한 프로젝트: **{p['name']}**\n\n"+answer
        elif text in ('업무','업무 변경') or (page_match and page_match[1]=='업무'):
            if not cid:answer,attachments=chat_ui.projects(context_key,user)
            else:
                outline.sync();answer,attachments=chat_ui.tasks(context_key,user,cid,int(page_match[2]) if page_match else 1)
        elif text.startswith('조회 '):
            outline.sync();ts=outline.tasks(permissions.project(user,cid)['id'],user);q=text[3:].strip() if text.startswith('조회 ') else ''
            answer='**'+permissions.project(user,cid)['name']+'**\n'+('\n'.join(f"`{t['code']}` [{t['title']}]({t['url']}) · {t['fields'].get('status','형식 오류')} · {t['fields'].get('progress','미기재')}" for t in ts if q in t['title']) or '등록된 업무가 없습니다. 포털에서 업무를 생성하세요.')
        elif text.startswith('작성 '):
            parts=text[3:].split('|',1)
            t=outline.create(user,parts[0].strip(),{'owner':user['email'],'status':'미착수','progress':'0%'},'rc:'+mid,
                             parts[1].strip() if len(parts)>1 else '',permissions.project(user,cid)['id'])
            answer=f"업무 등록 완료: [{t['title']}]({t['url']})\n업무 번호 `{t['code']}` · {t['collectionName']}\n관리자는 포털에서 완료 기준을 작성·분배할 수 있습니다."
        elif text.startswith('항목 ') or text.startswith('업무선택 ') or text in ('현재 업무','항목'):
            if text in ('현재 업무','항목') and not context.get('taskId'):
                answer,attachments=chat_ui.tasks(context_key,user,cid) if cid else chat_ui.projects(context_key,user)
                say(room,answer,attachments)
                with store.db() as c:c.execute('UPDATE messages SET state=? WHERE id=?',('DONE',mid))
                return
            outline.sync();d=outline.find(context['taskId'] if text in ('현재 업무','항목') else text.split(maxsplit=1)[1],permissions.project(user,cid)['id'],user)
            outline.can_report(user,d)
            context.update(collectionId=d['collectionId'],taskId=d['id']);store.put(context_key,context)
            chat_ui.clear_menu(context_key)
            items=criteria.parse(d['text'])
            labels=directory.names()
            answer=f"선택한 업무: **{permissions.project(user,d['collectionId'])['name']} → {d['title']}**\n**완료 기준**\n"+('\n'.join(f"{n}. {'☑' if i['state']=='완료' else '☐'} {i['title']} · {i['state']} · {labels.get(i['owner'],i['owner'])}{' (내 항목)' if i['owner']==user['email'].lower() else ''}" for n,i in enumerate(items,1)) or '완료 기준이 없는 업무입니다.')+'\n자신에게 배정된 항목의 진행 상황을 편하게 입력하세요. 다음 보고에도 이 업무를 기억합니다.'
            attachments=chat_ui.navigation()
        elif text.startswith('보고 '):
            # A real project may begin with "보고 "; preserve the complete input.
            answer,attachments=prepare_report(user,uid,room,context_key,context,text,mid,m.get('_workhub_received_at'))
        elif text.startswith('확정 '):
            p=outline.confirm(user,text.split(maxsplit=1)[1]);answer=p.get('formatted_report','')+f"\n\nOutline 반영 완료: {p['title']}\n원본: {p['url']}\n전체 진행률: {domain.parse(p['after'])['progress']} · 같은 업무의 진행 이력으로 기록했습니다."
            attachments=chat_ui.navigation()
        elif text.startswith('자료 '):
            say(room,'통합 업무 자료에서 근거를 검색 중입니다.')
            result=assistant.research(user,text[3:],permissions.project(user,cid)['id']);answer=result.get('display') or result.get('report') or json.dumps(result,ensure_ascii=False)[:9000]
        elif text=='주간보고':auth.admin(user);answer=outline.weekly(user,permissions.project(user,cid)['id'])
        elif len(text)>=5:
            answer,attachments=prepare_report(user,uid,room,context_key,context,text,mid,m.get('_workhub_received_at'))
        else:answer,attachments=chat_ui.projects(context_key,user)
        say(room,answer,attachments)
        with store.db() as c:c.execute('UPDATE messages SET state=? WHERE id=?',('DONE',mid))
    except job_control.Stopped as ex:
        with store.db() as c:c.execute('UPDATE messages SET state=? WHERE id=?',('CANCELLED',mid))
        say(room,str(ex)+'\n필요한 업무는 `내 업무`, 새 보고는 업무와 진행 상태를 적어 주세요.')
    except Exception as ex:
        detail=getattr(ex,'detail',None) or (str(ex) if isinstance(ex,ValueError) else '처리에 실패했습니다. 잠시 후 다시 시도하고 문제가 계속되면 관리자에게 문의하세요.')
        recovery=None
        if text.startswith('확정 '):
            try:
                pending=outline.proposal(user,text.split(maxsplit=1)[1])
                if pending['state']=='APPLYING':recovery=chat_ui.confirmation(context_key,pending)
            except Exception:pass
        try:say(room,report_chat.friendly_error(detail),recovery)
        except Exception:pass
        with store.db() as c:c.execute('UPDATE messages SET state=? WHERE id=?',('FAILED',mid))
        log.warning('message_failed type=%s detail=%s',type(ex).__name__,detail)

def consume():
    while True:
        m=JOBS.get()
        received=m.get('_workhub_received_at')
        try:
            with execution.request('bot_message',wait_seconds=time.monotonic()-received if received else 0):handle(m)
        finally:JOBS.task_done()

def control(m):
    uid=m['u']['_id'];room=m['rid'];mid=m['_id']
    with store.db() as c:
        if c.execute('SELECT 1 FROM messages WHERE id=?',(mid,)).fetchone():return
        c.execute('INSERT INTO messages VALUES(?,?,?)',(mid,'DONE',store.dump(m)))
    answer=job_control.stop(uid,room,m['msg'].strip(),m['_workhub_received_at'])
    say(room,answer)


def consume_controls():
    while True:
        m=CONTROLS.get()
        try:control(m)
        except Exception:log.exception('emergency_cancel_failed')
        finally:CONTROLS.task_done()


def receive(m):
    uid=m.get('u',{}).get('_id');room=m.get('rid');text=m.get('msg','').strip()
    if not uid or uid==bot_id or not m.get('_id') or m.get('t') or not room or not text:return
    import sys
    if knowledge_chat.enqueue(m,sys.modules[__name__]):return
    urgent=text in ('긴급 취소','긴급취소','중단') or text.startswith('긴급 취소 ·') or (text=='취소' and job_control.has_active(uid,room))
    target=CONTROLS if urgent else JOBS
    try:target.put_nowait({**m,'_workhub_received_at':time.monotonic()})
    except queue.Full:log.warning('message_queue_full')

def run():
    global headers,bot_id,stream,mongo
    workers_started=False
    while True:
        try:
            creds={'user':os.environ['BOT_USERNAME'],'password':os.environ['BOT_PASSWORD']}
            login=api('login',creds)['data'];bot_id=login['userId']
            headers={'X-User-Id':bot_id,'X-Auth-Token':login['authToken']}
            mongo=MongoClient(os.environ['MONGO_URL'],serverSelectionTimeoutMS=5000)
            stream=RoomMessageStream(URL,creds['user'],creds['password'],[],receive);stream.start()
            if not workers_started:
                import sys
                knowledge_chat.start(sys.modules[__name__])
                threading.Thread(target=consume,daemon=True).start()
                threading.Thread(target=consume_controls,daemon=True).start()
                workers_started=True
            while True:
                subs=api('subscriptions.get')['update']
                # Drop subscriptions after leaving or archiving a room, including on reconnect.
                subs=[s for s in subs if s.get('t')=='d' or (knowledge_chat.enabled() and s.get('t') in ('c','p') and not (mongo.rocketchat.rocketchat_room.find_one({'_id':s['rid']}) or {}).get('archived'))]
                current_rooms={s['rid'] for s in subs}
                if stream.room_ids-current_rooms:
                    retained=stream.room_ids & current_rooms
                    stream.stop()
                    stream=RoomMessageStream(URL,creds['user'],creds['password'],retained,receive)
                    stream.start()
                for sub in subs:
                    eligible=sub.get('t')=='d' or (knowledge_chat.enabled() and sub.get('t') in ('c','p'))
                    if eligible and stream.add_room(sub['rid']):
                        # Catch the first DM sent before discovery/subscription, and a bounded offline backlog.
                        endpoint='im.history' if sub.get('t')=='d' else 'channels.history' if sub.get('t')=='c' else 'groups.history'
                        messages=api(endpoint+'?roomId='+quote(sub['rid'])+'&count=100').get('messages',[])
                        for m in reversed(messages):receive(m)
                store.put('bot_status',{'at':store.now(),'connected':stream.connected.is_set(),'rooms':len(stream.room_ids)})
                time.sleep(10)
        except Exception as ex:
            log.warning('bot_reconnect type=%s',type(ex).__name__)
            if stream:stream.stop()
            time.sleep(15)
