"""Native Rocket.Chat attachment buttons bound to one authenticated DM context."""
import hashlib,math
from datetime import datetime,timezone,timedelta
from . import store,outline,auth,permissions
from legacy_app.rocketchat.draft import safe_text

PAGE_SIZE=8

def button(label,message):
    label={'업무':'← 업무 다시 선택','프로젝트':'↖ 프로젝트 변경'}.get(message,label)
    return {'type':'button','text':label,'msg':message,'msg_in_chat_window':True,'msg_processing_type':'sendMessage'}

def key(context,command):
    return 'chat-choice:'+hashlib.sha256((context+'\0'+command).encode()).hexdigest()

def bind(context,label,command,target):
    # Human-readable command is bound once. A later menu must never repoint an
    # old button at a different document/proposal, including duplicate names.
    base=command;n=1
    while True:
        saved=store.get(key(context,command))
        if saved is None or saved==target:break
        n+=1;command=f'{base} ({n})'
    store.put(key(context,command),target)
    return button(label if n==1 else f'{label} ({n})',command)

def resolve(context,command):return store.get(key(context,command))

def attachment(actions,title='선택하세요',color='#2563eb'):
    return [{'title':title,'color':color,'button_alignment':'vertical','actions':actions}]

def navigation():
    return attachment([button('현재 업무 · 완료 기준','현재 업무')],'현재 업무 확인')+back_navigation()

def back_navigation():
    return attachment([button('업무 다시 선택','업무')],'같은 프로젝트의 다른 업무','#64748b')+attachment([button('프로젝트 변경','프로젝트')],'프로젝트 목록으로 돌아가기','#7c3aed')

def reportable(user,task):
    if task.get('error'):return False
    if user.get('admin'):return True
    items=task.get('criteria',[])
    return any(i['owner']==user['email'].lower() for i in items) if items else task['fields'].get('owner','').lower()==user['email'].lower()

def menu(context,rows,kind,page=1,project=None):
    pages=max(1,math.ceil(len(rows)/PAGE_SIZE));page=max(1,min(page,pages))
    actions=[];lines=[]
    for n,row in enumerate(rows[(page-1)*PAGE_SIZE:page*PAGE_SIZE],1):
        title=row['name'] if kind=='project' else row['title']
        target={'kind':kind,'id':row['id']}
        if project:target['collectionId']=project['id']
        command=('프로젝트 선택 · '+title) if kind=='project' else ('업무 선택 · '+project['name']+' / '+title)
        actions.append(bind(context,title,command,target))
        suffix='' if kind=='project' else ' · '+row['fields'].get('progress','미기재')
        lines.append(f'{n}. {safe_text(title)}{suffix}')
    store.put('chat-menu:'+context,[a['msg'] for a in actions])
    word='프로젝트' if kind=='project' else '업무'
    if page>1:actions.append(button('이전 목록',f'{word} 목록 {page-1}쪽'))
    if page<pages:actions.append(button('다음 목록',f'{word} 목록 {page+1}쪽'))
    if kind=='task':actions.append(button('프로젝트 변경','프로젝트'))
    heading='**보고할 프로젝트를 선택하세요.**' if kind=='project' else '**'+safe_text(project['name'])+' · 보고할 업무를 선택하세요.**'
    if not rows:lines=['배정된 보고 업무가 없습니다. 팀장에게 완료 기준 배정을 요청하세요.']
    text=heading+'\n'+'\n'.join(lines)+f'\n\n이름 버튼을 누르세요. 버튼 대신 위 목록의 숫자만 입력해도 됩니다. ({page}/{pages}쪽)'
    # Current web clients squeeze multiple actions into one row, even when
    # vertical alignment is requested. A separate attachment keeps names legible.
    return text,[{'color':'#7c3aed' if action.get('msg')=='프로젝트' else '#2563eb','actions':[action]} for action in actions]

def projects(context,user,page=1):return menu(context,permissions.projects(user),'project',page)

def tasks(context,user,collection_id,page=1):
    project=permissions.project(user,collection_id)
    rows=[t for t in outline.tasks(project['id'],user) if reportable(user,t)]
    return menu(context,rows,'task',page,project)

def numbered(context,text):
    options=store.get('chat-menu:'+context,[])
    if not text.isdecimal():return text
    n=int(text)
    if not 1<=n<=len(options):raise ValueError('현재 목록에 있는 숫자를 입력하거나 이름 버튼을 눌러주세요.')
    return options[n-1]

def clear_menu(context):store.put('chat-menu:'+context,[])

def confirmation(context,p):
    stamp=datetime.fromisoformat(p.get('created',store.now())).astimezone(timezone(timedelta(hours=9))).strftime('%m/%d %H:%M:%S')
    checking=p.get('state')=='APPLYING'
    action=bind(context,'반영 결과 다시 확인' if checking else '이 보고 확정',f'보고 확정 · {p["title"]} · {stamp}',{'kind':'confirm','id':p['id'],'taskId':p['doc_id']})
    cancel=bind(context,'이 초안 취소',f'보고 취소 · {p["title"]} · {stamp}',{'kind':'cancel','id':p['id'],'taskId':p['doc_id']})
    return attachment([action] if checking else [action,cancel],'저장 요청의 반영 결과를 다시 확인하세요' if checking else '보고 내용을 확인한 뒤 확정하거나 취소하세요')+attachment([
        {'type':'button','text':'변경 내용 자세히 보기','url':auth.BASE+'/#proposal-'+p['id']},
        button('현재 업무 · 완료 기준','현재 업무')],'현재 보고 확인')+back_navigation()
