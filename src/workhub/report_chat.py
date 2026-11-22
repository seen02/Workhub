"""A report first, then one next step. Technical diagnostics stay in the journal."""
import logging
from datetime import datetime,timezone,timedelta
from . import reports,report_transport,chat_ui,store,outline,permissions,job_control

log=logging.getLogger('workhub.reports')
INTRO='**오늘 한 일을 편하게 적어 주세요.**\n예: 시연 프로젝트의 로그인은 화면을 끝냈고 오류 안내는 확인 중이야.\n\n할 일을 먼저 확인하려면 `내 업무`를 입력하세요. 기한 초과·오늘 마감·예정·마감일 미정 업무와 내 완료 기준을 모아 보여드려요.\n\n보고문을 확인하고 **보고 및 반영**을 누른 뒤 채널을 고르면 됩니다.\n최근 보고는 `보고 현황`으로 다시 볼 수 있어요.'

def action(context,r,label,op,**extra):
    target={'kind':'report-v2','id':r['id'],'version':r['version'],'op':op,**extra}
    stamp=datetime.fromisoformat(r['when']).astimezone(timezone(timedelta(hours=9))).strftime('%m/%d %H:%M')
    # Human-readable action receipts; immutable bindings still carry IDs/version.
    result=chat_ui.bind(context,label,f'보고 · {label} · {stamp}',target)
    result['text']=label
    return result

def buttons(actions,size=3):
    return [{'color':'#e2e8f0','button_alignment':'horizontal','actions':actions[n:n+size]} for n in range(0,len(actions),size)]

def can_edit(r):
    try:reports.editable(r);return True
    except ValueError:return False

def pending(r):return [(n,g) for n,g in enumerate(r['groups']) if g['state'] not in ('APPLIED','SKIPPED')]

def friendly_error(detail):
    s=str(detail)
    if any(w in s for w in ('수정 전 버튼','유효한 보고 버튼')):return '이전 보고의 버튼이에요. 가장 최근 버튼을 눌러 주세요.'
    if any(w in s for w in ('결과 확인','이미 전송','전송을 시작')):return '이미 처리한 보고예요. 고칠 내용은 새 보고로 적어 주세요.'
    if '본인의 보고 초안' in s:return '최근 보고가 없어요. 오늘 한 일을 먼저 적어 주세요.'
    if any(w in s for w in ('LLM','AI가','AI 처리')):return '다른 보고를 정리하고 있어요. 잠시 후 다시 보내 주세요.'
    if any(w in s for w in ('해석','완료 기준 연결','원문에 없는')):return '어떤 업무를 끝냈고 무엇을 하고 있는지 다시 적어 주세요.'
    if '9,000' in s or '너무 깁' in s or '내용과 기준이 많' in s:return '보고가 길어요. 업무를 나눠서 보내 주세요.'
    return s

def issue(g):
    """Never render model questions, raw exception strings or implementation states."""
    reason=str(g.get('error') or g.get('issue') or '')
    if g.get('creation',{}).get('attempted') and g['state']!='APPLIED':return '저장됐는지 확인하고 있어요. 다시 만들지 말고 아래에서 확인해 주세요.'
    if g['state']=='CONFLICT' or any(w in reason for w in ('원문','바뀌었','변경되')):return '문서가 바뀌었어요. 보고 내용을 다시 확인해 주세요.'
    if any(w in reason for w in ('권한','담당자','배정')):return '이 업무를 수정할 수 없어요. 담당자나 관리자에게 확인해 주세요.'
    if not g.get('project_id'):return '어느 프로젝트의 업무인지 골라 주세요.'
    if any(w in reason for w in ('상태 해석','완료 기준','기준명','상태가 서로','중복')):return '어떤 항목을 끝냈고 무엇을 하고 있는지 다시 적어 주세요.'
    if g['kind']=='unresolved':return '어느 업무인지 골라 주세요.'
    return '저장하지 못했어요. 잠시 후 다시 눌러 주세요.'

def journal(r):
    log.info('report_view id=%s version=%s search=%s posting=%s groups=%s',r['id'],r['version'],r.get('search_mode'),r['posting']['state'],
      [{'kind':g['kind'],'state':g['state'],'issue':g.get('issue'),'error':g.get('error')} for g in r['groups']])

def view(context,r,receipt=False):
    journal(r);posted=r['posting']['state']=='POSTED';remaining=pending(r);done=not remaining
    ambiguous=next((n for n,g in remaining if g.get('needs_task_choice')),None)
    if ambiguous is not None and can_edit(r):return candidate_menu(context,r,ambiguous)
    editable=can_edit(r);dest=r.get('destination');problem=next(((n,g) for n,g in remaining if g['kind']=='unresolved' or g['state'] in ('FAILED','CONFLICT')),None)
    lines=[];actions=[]
    if not receipt and not (posted and done):lines.append(reports.text(r))
    if posted:
        lines.append('**'+reports.clean(dest['name'])+'에 보고했어요.**')
    if done:
        count=sum(g['state']=='APPLIED' for g in r['groups'])
        lines.append(f'**업무 {count}건을 저장했어요.**' if count else '이번 보고는 업무에 저장하지 않아요.')
    elif receipt and any(g['state']=='APPLIED' for g in r['groups']):
        lines.append(f"{sum(g['state']=='APPLIED' for g in r['groups'])}건은 저장했어요. 나머지를 확인해 주세요.")
    new=[reports.group_title(r,g) for _,g in remaining if g['kind']=='create' and not g.get('creation')]
    if new:lines.append('새로 만들 내 업무: **'+', '.join(new)+'**')
    excluded=[reports.clean(g['title']) for g in r['groups'] if g['state']=='SKIPPED']
    if excluded:lines.append('업무에 저장하지 않음: '+', '.join(excluded))
    uncertain=r['posting']['state'] in ('POSTING','UNKNOWN')
    if uncertain:lines.append('보고가 전송됐는지 확인하고 있어요. 다시 보내지 말고 **전송 확인**을 눌러 주세요.')
    if problem:
        n,g=problem;lines.append('**'+reports.group_title(r,g)+'** — '+issue(g))
        if editable:
            actions.append(action(context,r,'내용 고치기','edit'))
            actions.append(action(context,r,'업무 고르기' if g.get('project_id') else '프로젝트 고르기','tasks' if g.get('project_id') else 'projects',index=n))
        else:actions.append(action(context,r,'다시 확인','submit'))
    elif uncertain:actions.append(action(context,r,'전송 확인','submit'))
    elif not posted:actions.append(action(context,r,'보고 및 반영','destinations'))
    elif not done:actions.append(action(context,r,'반영 다시 시도','submit'))
    if posted:actions.append({'type':'button','text':'보고 보기','url':r['posting']['url']})
    elif editable and not problem:actions.append(action(context,r,'수정','edit'))
    if done:
        if any(g.get('result',{}).get('url') for g in r['groups']):actions.append(action(context,r,'업무 보기','documents'))
        if posted:actions.append(action(context,r,'새 보고','new'))
    if editable:
        actions.extend([action(context,r,'업무 바꾸기','pick'),action(context,r,'취소','cancel')])
    elif not done:actions.append(action(context,r,'새 보고','new'))
    if posted:actions.append(chat_ui.button('내 업무 다시 보기','내 업무'))
    chat_ui.clear_menu(context)
    return '\n\n'.join(lines),buttons(actions,size=4)

def candidate_menu(context,r,index,page=1):
    g=r['groups'][index];options=g['options'];size=6
    pages=max(1,(len(options)+size-1)//size);page=max(1,min(page,pages));actions=[]
    for offset,row in enumerate(options[(page-1)*size:page*size],(page-1)*size+1):
        label=row['project']
        if sum(x['project']==label for x in options)>1:label+=f' · {row["title"]} ({offset})'
        actions.append(action(context,r,label,'candidate',index=index,target=row['id']))
    if page>1:actions.append(action(context,r,'이전','candidates',index=index,page=page-1))
    if page<pages:actions.append(action(context,r,'다음','candidates',index=index,page=page+1))
    actions.extend([action(context,r,'내용 고치기','edit'),action(context,r,'취소','cancel')])
    store.put('chat-menu:'+context,[a['msg'] for a in actions])
    text=f'**{reports.clean(g["title"])}** 업무가 여러 곳에 있어요.\n어느 프로젝트의 업무를 보고할까요?\n\n입력한 내용은 보관했어요. 선택하면 해당 업무로 보고문을 정리할게요.'
    if pages>1:text+=f'\n{page}/{pages}쪽'
    return text,buttons(actions)


def more(context,r):
    # Existing messages may still have a bound "더보기" button.
    return view(context,r)

def menu(context,r,rows,op,label,page=1,index=None):
    size=6;pages=max(1,(len(rows)+size-1)//size);page=max(1,min(page,pages));choices=[]
    for row in rows[(page-1)*size:page*size]:
        choices.append(action(context,r,row['name'],op,target=row['id'],**({'index':index} if index is not None else {})))
    if page>1:choices.append(action(context,r,'이전',label,page=page-1,**({'index':index} if index is not None else {})))
    if page<pages:choices.append(action(context,r,'다음',label,page=page+1,**({'index':index} if index is not None else {})))
    if index is not None:
        if label=='tasks':choices.append(action(context,r,'새 업무로 추가','create',index=index))
        if label!='projects':choices.append(action(context,r,'다른 프로젝트','projects',index=index))
        choices.append(action(context,r,'이 업무는 저장 안 함','skip',index=index))
    choices.append(action(context,r,'뒤로 가기' if label=='destinations' else '돌아가기','view'))
    store.put('chat-menu:'+context,[a['msg'] for a in choices])
    title='어디에 보고할까요?' if label=='destinations' else ('프로젝트를 골라 주세요.' if label=='projects' else '어느 업무인가요?')
    if label=='destinations':title+='\n**채널을 누르면 보고를 보내고 업무에도 반영해요.**'
    if index is not None:title='**'+reports.clean(r['groups'][index]['title'])+'**\n'+title
    if pages>1:title+=f' ({page}/{pages})'
    if not rows:title+='\n'+('보고할 방에 본인과 통합 업무 비서를 초대해 주세요.' if label=='destinations' else '선택할 항목이 없어요.')
    return title,buttons(choices)

def route(user,uid,dm,context_key,context,text,choice):
    if choice and choice.get('kind')=='report-v2':
        report_transport.require_dm(user,uid,dm)
        r=reports.get(user,choice['id'],choice['version'])
        if r['dm']!=dm:raise ValueError('보고를 작성한 개인 대화방에서 진행해 주세요.')
        op=choice['op'];n=choice.get('index',0)
        if any(g.get('needs_task_choice') for _,g in pending(r)) and op in ('publish','apply','submit','destination','destinations','submit_destination'):
            return view(context_key,r)
        if op in ('publish','apply','submit'):
            # Old buttons also follow the combined flow. Never reuse a saved channel silently.
            if r['posting']['state'] in ('NOT_POSTED','FAILED'):
                return menu(context_key,r,report_transport.destinations(user,uid),'submit_destination','destinations')
            r=reports.submit(user,r['id'],r['version'])
        elif op=='destination':
            return menu(context_key,r,report_transport.destinations(user,uid),'submit_destination','destinations')
        elif op=='submit_destination':
            r=reports.submit(user,r['id'],r['version'],choice['target'])
        elif op=='more':return more(context_key,r)
        elif op=='pick':
            return '바꿀 업무를 골라 주세요.',buttons([action(context_key,r,reports.group_title(r,g),'tasks',index=i) for i,g in enumerate(r['groups']) if g['state']!='APPLIED']+[action(context_key,r,'돌아가기','view')])
        elif op=='documents':
            return '저장한 업무를 열어 보세요.',buttons([{'type':'button','text':reports.group_title(r,g),'url':g['result']['url']} for g in r['groups'] if g.get('result',{}).get('url')]+[action(context_key,r,'돌아가기','view')])
        elif op=='new':
            context.pop('editingReport',None);store.put(context_key,context);chat_ui.clear_menu(context_key)
            return INTRO,None
        elif op=='edit':
            reports.editable(r);context['editingReport']={'id':r['id'],'version':r['version']};store.put(context_key,context)
            return '아래 내용을 고쳐서 다시 보내 주세요.\n\n'+r['raw'],buttons([action(context_key,r,'수정 안 함','view')])
        elif op=='cancel':
            reports.cancel(user,r['id'],r['version']);context.pop('editingReport',None);context.pop('reportId',None);store.put(context_key,context)
            return '보고를 취소했어요. 다시 작성하려면 오늘 한 일을 적어 주세요.',None
        elif op=='destinations':return menu(context_key,r,report_transport.destinations(user,uid),'submit_destination','destinations',choice.get('page',1))
        elif op=='projects':return menu(context_key,r,permissions.projects(user),'project','projects',choice.get('page',1),n)
        elif op=='tasks':
            g=r['groups'][n]
            if not g.get('project_id'):return menu(context_key,r,permissions.projects(user),'project','projects',1,n)
            rows=[{'id':t['id'],'name':t['title']} for t in outline.tasks(g['project_id'],user) if not t.get('error') and chat_ui.reportable(user,t)]
            return menu(context_key,r,rows,'task','tasks',choice.get('page',1),n)
        elif op=='candidates':return candidate_menu(context_key,r,n,choice.get('page',1))
        elif op in ('task','candidate','project','create','skip'):
            r=reports.choose(user,r['id'],r['version'],n,op,choice.get('target',''))
        context['reportId']=r['id'];context.pop('editingReport',None);store.put(context_key,context)
        return view(context_key,r,receipt=op in ('publish','apply','submit','destination','submit_destination'))
    if text.startswith(('보고 도구 ·','보고 ·')):raise ValueError('가장 최근 보고의 버튼을 눌러 주세요.')
    if text in ('보고','새 보고','시작','메뉴','시연'):
        context.pop('editingReport',None);context['reportMode']=True;store.put(context_key,context);chat_ui.clear_menu(context_key)
        return INTRO,None
    if text=='보고 현황':return view(context_key,reports.get(user,context.get('reportId','')))
    if text.startswith('보고할 곳'):
        r=reports.get(user,context.get('reportId',''))
        return menu(context_key,r,report_transport.destinations(user,uid,text[len('보고할 곳'):].strip()),'submit_destination','destinations')
    return None

def draft(user,uid,dm,context_key,context,text,mid):
    report_transport.require_dm(user,uid,dm)
    edit=context.get('editingReport')
    if edit:r=reports.revise(user,edit['id'],edit['version'],text)
    else:r=reports.create(user,text,'rc:'+mid,uid,dm,{'project_id':context.get('collectionId',''),'task_id':context.get('taskId','')})
    job_control.check()
    context['reportId']=r['id'];context.pop('editingReport',None);store.put(context_key,context)
    return view(context_key,r)
