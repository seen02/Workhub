"""Mention-only channel search on an independent, bounded worker."""
import hashlib, json, os, queue, re, threading, time, uuid
from datetime import datetime, timezone
from fastapi import HTTPException
from . import execution, knowledge, permissions, store

JOBS=queue.Queue(maxsize=20)
STARTED=False
LOCK=threading.RLock()


def enabled():return knowledge.enabled() and os.getenv('ROCKETCHAT_KNOWLEDGE_ENABLED','false').lower()=='true'


def mention(message,bot_id):
    return any(m.get('_id')==bot_id for m in message.get('mentions',[]) if isinstance(m,dict))


def eligible(message,b):
    if not enabled():return False
    room=b.mongo.rocketchat.rocketchat_room.find_one({'_id':message.get('rid')}) or {}
    if room.get('t') in ('c','p'):return True  # Reserve channel messages so they never become reports.
    text=message.get('msg','').strip()
    # A report such as "문서 요약 완료" must stay in the existing report flow.
    requested=bool(re.search(r'(문서|자료).*(?:링크|주소).*(?:줘|주세요|부탁)|(?:문서|자료).*(?:찾아|검색해|요약해)\s*(?:줘|주세요)',text))
    return room.get('t')=='d' and (text.startswith(('자료 ','문서 검색 ','검색 선택 · ')) or requested)


def enqueue(message,b):
    if not eligible(message,b):return False
    room=b.mongo.rocketchat.rocketchat_room.find_one({'_id':message.get('rid')}) or {}
    if room.get('t') in ('c','p') and not mention(message,b.bot_id) and not message.get('msg','').startswith('검색 선택 · '):return True
    if message.get('editedAt'):return True
    try:JOBS.put_nowait(message)
    except queue.Full:
        # No privileged content is included in the overload notice.
        send(b,message['rid'],'검색 요청이 많아요. 잠시 후 다시 시도해 주세요.',message['_id']+':busy',message.get('tmid') or message['_id'])
    return True


def send(b,rid,text,key,thread=None,attachments=None):
    mid='ks'+hashlib.sha256(key.encode()).hexdigest()[:28]
    old=b.mongo.rocketchat.rocketchat_message.find_one({'_id':mid})
    if old:
        if old.get('rid')!=rid:raise HTTPException(409,'검색 응답 위치가 변경되었습니다.')
        return mid
    message={'_id':mid,'rid':rid,'msg':text[:9000]}
    if thread:message['tmid']=thread
    if attachments:message['attachments']=attachments
    try:b.api('chat.sendMessage',{'message':message})
    except Exception:
        if not b.mongo.rocketchat.rocketchat_message.find_one({'_id':mid}):raise
    return mid


def public(user,room,documents,b):
    # Explicit room-to-collection disclosure policy. Membership alone is insufficient.
    rules=store.get('knowledge:channel-policy',{})
    permitted=set(rules.get(room['_id'],[]))
    if not documents or any(d['collection_id'] not in permitted for d in documents):return False
    access=knowledge.access(user)
    for d in documents:
        if not access.readable(d['collection_id']):return False
    return True


def process(m,b):
    uid=m['u']['_id'];rid=m['rid'];mid=m['_id'];key='knowledge:chat:'+mid
    previous=store.get(key)
    if previous and previous.get('state')=='done':return
    raw=b.mongo.rocketchat.rocketchat_message.find_one({'_id':mid,'rid':rid,'u._id':uid})
    if not raw or raw.get('msg')!=m.get('msg'):return
    # Do not publish responses to historical mentions when enabling/reconnecting.
    timestamp=raw.get('ts')
    if isinstance(timestamp,datetime) and time.time()-timestamp.replace(tzinfo=timezone.utc).timestamp()>600:return
    room=b.mongo.rocketchat.rocketchat_room.find_one({'_id':rid}) or {}
    if room.get('archived') or room.get('encrypted'):return
    from . import report_transport
    user=b.identity(uid)
    is_dm=room.get('t')=='d'
    if is_dm:report_transport.require_dm(user,uid,rid)
    elif not report_transport.permitted(b,uid,room) or not report_transport.permitted(b,b.bot_id,room):return
    text=raw['msg'].strip();cid=''
    if text.startswith('검색 선택 · '):
        token=text.split(' · ',1)[1];choice=store.get('knowledge:choice:'+token)
        if not choice or choice['uid']!=uid or choice['rid']!=rid or choice['expires']<time.time():
            send(b,rid,'선택이 만료되었어요. 문서를 다시 검색해 주세요.',mid+':expired',None if is_dm else raw.get('tmid') or mid);return
        text=choice['query'];cid=choice['cid']
    else:
        if not is_dm and not mention(raw,b.bot_id):return
        text=re.sub(r'@'+re.escape(os.environ['BOT_USERNAME'])+r'\b','',text).strip()
        text=re.sub(r'^(자료|문서 검색)\s+','',text)
    if not text:return
    thread=None if is_dm else raw.get('tmid') or mid
    if not is_dm and re.search(r'보고(?:해|하기|\s*및)|반영해',text):
        send(b,rid,'업무 보고는 통합 업무 비서 개인 대화방에서 진행해 주세요.',mid+':report',thread);return
    store.put(key,{'state':'running','at':time.time()})
    try:
        mode='answer' if re.search(r'요약|어떻게|왜|설명|비교',text) and not re.search(r'링크|주소',text) else 'links'
        with execution.request('knowledge_chat',user):result=knowledge.execute(user,{'query':text,'collection_id':cid,'mode':mode})
        documents=result.get('documents',[])
        with execution.request('knowledge_chat_publish',user):
            user=knowledge.current_user(user['sub']);knowledge.validate(user,result)
            room=b.mongo.rocketchat.rocketchat_room.find_one({'_id':rid}) or {}
            if not is_dm and (not report_transport.permitted(b,uid,room) or not report_transport.permitted(b,b.bot_id,room)):return
            to_dm=not is_dm and not public(user,room,documents,b)
            destination=rid
            if to_dm:
                dm=b.api('im.create',{'usernames':raw['u']['username']});destination=dm['room']['_id']
                report_transport.require_dm(user,uid,destination)
            attachments=[]
            if result.get('status')=='choose':
                actions=[]
                for c in result['choices'][:8]:
                    token=uuid.uuid4().hex
                    store.put('knowledge:choice:'+token,{'uid':uid,'rid':destination,'cid':c['id'],'query':text,'expires':time.time()+600})
                    actions.append({'type':'button','text':c['name'],'msg':'검색 선택 · '+token,'msg_in_chat_window':True})
                attachments=[{'actions':actions}]
            answer=result.get('answer','') if mode=='answer' or not documents else '문서를 찾았어요.'
            for d in documents:
                title=re.sub(r'[\[\]\r\n]',' ',d['title'])
                answer+='\n\n'+f"📄 [{title}]({d['url']})"+'\n'+d.get('collection','')
            if not answer:answer='선택한 범위에서 문서를 찾지 못했어요.'
            send(b,destination,answer,mid+':result',None if to_dm or is_dm else thread,attachments)
            if to_dm:send(b,rid,'검색 결과는 개인 대화방으로 안내했어요.',mid+':dm',thread)
        store.put(key,{'state':'done','at':time.time()})
    except Exception:
        store.put(key,{'state':'failed','at':time.time()})
        send(b,rid,'검색 결과를 전달하지 못했어요. 개인 대화방에서 다시 요청해 주세요.',mid+':error',thread)
        b.log.exception('knowledge_search_failed')


def start(b):
    global STARTED
    with LOCK:
        if STARTED:return
        STARTED=True
    def worker():
        while True:
            m=JOBS.get()
            try:process(m,b)
            except Exception:b.log.exception('knowledge_search_worker_failed')
            finally:JOBS.task_done()
    threading.Thread(target=worker,daemon=True,name='knowledge-chat').start()
