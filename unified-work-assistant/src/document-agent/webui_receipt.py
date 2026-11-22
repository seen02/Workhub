"""Scoped full results for display; compact history for the 4K routing model."""
import json
import re
import uuid
import httpx
from pydantic import BaseModel

def plain(value):
    return '\n'.join(x.get('text','') for x in value if x.get('type')=='text') if isinstance(value,list) else value or ''

def question_text(error):
    if not isinstance(error,dict): return str(error)
    text=error.get('message','위치를 확인해 주세요.')
    for i,c in enumerate(error.get('candidates',[]),1):
        text+='\n'+str(i)+'. '+(c.get('path') or c.get('name') or c.get('title') or '')
    return text

def failure_text(error):
    if not isinstance(error,dict) or not error.get('candidate'):
        return '**작업을 완료하지 못했습니다**\n\n'+question_text(error)
    content='**검토가 필요한 초안 · Outline에는 저장하지 않았습니다**\n\n'
    content+=error['candidate']+'\n\n---\n### 확인이 필요한 부분\n\n'
    if error.get('partial'):
        content+=f"전체 {error['total_parts']}부분 중 {error['processed_parts']}부분까지 작성한 초안입니다. 이후 부분은 아직 작성하지 못했습니다.\n\n"
    content+='자동 검증을 통과하지 못했지만, 작성한 내용을 위에 남겨두었습니다. 검증 모델의 지적이 맞는지도 원문과 비교해 주세요.\n\n'
    issues=error.get('issues',[])
    if issues: content+='\n'.join('- '+str(issue) for issue in issues)+'\n'
    if error.get('missing_numbers'): content+='\n- 원문에서 누락된 숫자: '+', '.join(map(str,error['missing_numbers']))
    if error.get('extra_numbers'): content+='\n- 원문·양식 외에 추가된 숫자: '+', '.join(map(str,error['extra_numbers']))
    if not issues and not error.get('missing_numbers') and not error.get('extra_numbers'):
        content+=error.get('message','검증 상세 사유를 확인하지 못했습니다.')
    content+='\n\n초안은 이 채팅에서 확인·복사할 수 있습니다. 수정해 다시 요청하려면 위 초안과 원문을 함께 사용하세요.'
    return content

class Filter:
    class Valves(BaseModel):
        AGENT_URL: str = 'http://document-agent:8000'
        AGENT_TOKEN: str = ''
    def __init__(self): self.toggle=False;self.valves=self.Valves()

    async def backend(self,path,body,user,metadata,arguments=None):
        chat=(metadata or {}).get('chat_id') or body.get('chat_id')
        if not chat or not user or not self.valves.AGENT_TOKEN: return None
        bridge=Tools();bridge.valves=bridge.Valves(AGENT_URL=self.valves.AGENT_URL,AGENT_TOKEN=self.valves.AGENT_TOKEN)
        headers=await bridge._identity_headers(user)
        async with httpx.AsyncClient(timeout=10) as c:
            r=await c.post(self.valves.AGENT_URL+'/agent/'+path,headers=headers,
                json={'tool':path,'arguments':arguments or {},'user_id':user['id'],'chat_id':chat})
            r.raise_for_status();return r.json()

    async def inlet(self,body:dict,__user__:dict=None,__metadata__:dict=None,__event_emitter__=None)->dict:
        if body.get('model')!='outline-assistant': return body
        messages=body.get('messages',[])
        raw=next((plain(m.get('content')) for m in reversed(messages) if m.get('role')=='user'),'')
        source=re.search(r'(?:메모(?:\s*원문)?|원문)\s*[:：]',raw)
        request=raw[:source.start()] if source else raw
        hint='';allowed=None;context={}
        try: context=await self.backend('context',body,__user__,__metadata__) or {}
        except Exception: pass
        if not source and '초안' not in request and ((context.get('edit_pending') and re.fullmatch(r'(?:변경|수정)?\s*(?:내용을?\s*)?(?:적용|확정|저장)(?:해줘|해\s*줘|해주세요|할게)?[.!\s]*',request)) or (re.search(r'바꿔|바꾸|수정|변경|교체',request) and re.search(r'문서|https?://[^\s]+/doc/',request))):
            allowed={'outline_edit'};hint='edit_request로 문서 선택과 변경 구절을 검증합니다.'
        elif context.get('workflow',{}).get('choices') and re.match(r'^\s*\d+\s*번?',request):
            allowed={'outline_write'};hint='manage_outline_document로 선택 답변을 전달하고 기존 작업 재개.'
        elif re.search(r'재시도|다시.*시도|저장만|초안.*(?:수정|다듬|보여)|(?:\d+시).*바꿔|없으면.*만들',request):
            allowed={'outline_write'};hint='manage_outline_document로 이전 작업 이어서 처리.'
        elif re.search(r'문서\s*(?:ID|아이디)|https?://[^\s]+/doc/',request,re.I) and re.search(r'수정|바꿔|변경',request):
            allowed={'outline_read','outline_edit'};hint='기존 문서 수정: read_outline_document 다음 revise_outline_document.'
        elif not source and '초안' not in request and re.search(r'기존|저장된',request) and re.search(r'문서',request) and re.search(r'수정|바꿔|변경',request):
            allowed={'outline_read','outline_edit'};hint='read_outline_document로 실제 문서 확인 후 revise_outline_document.'
        elif re.search(r'첨부(?:한|된|\s*문서|\s*파일)',request):
            allowed={'outline_write'};hint='사용자가 첨부파일 작업을 요청했습니다. 파일 내용은 입력 메시지에 표시되지 않습니다. manage_outline_document를 반드시 먼저 호출하세요. 첨부가 없다는 판단은 이 도구가 합니다. 사용자에게 본문을 다시 요구하지 마세요.'
        elif re.search(r'저장|넣어|등록',request) and not source and not re.search(r'저장하지|저장\s*금지',request) and context.get('latest_draft'):
            allowed={'outline_write'};hint='manage_outline_document로 저장 요청 전체를 전달.'
        elif source or '초안' in request or (re.search(r'템플릿|양식',request) and re.search(r'정리|작성|저장|넣어',request)):
            allowed={'outline_write'};hint='manage_outline_document로 사용자 원문 전체 전달.'
        elif re.search(r'찾|검색|종합|정리|알려|보고|상태|문제|목록|문서함|컬렉션|양식|읽|출처|보여|확정|됐|언제|누가|얼마|할 일|도착|중지|멈춰|취소|조사.*이어서',request): allowed={'outline_read'}
        if allowed is not None: body['tool_ids']=[x for x in body.get('tool_ids',[]) if x in allowed]
        users=[m for m in messages if m.get('role')=='user']
        systems=[m for m in messages if m.get('role')=='system']
        recent=[]
        if len(users)>1: recent.append({'role':'user','content':'이전 요청: '+plain(users[-2].get('content'))[:400]})
        if users: recent.append(users[-1])
        state='대화 상태: '+json.dumps(context,ensure_ascii=False)+'. '
        if context.get('latest_topic'): state+='새 주제를 말하지 않은 후속 보고/질문이면 research_outline(topic="")으로 이전 조사 재사용. 새 컬렉션을 추측하지 마세요. '
        state+='컬렉션 생략 시 검색은 전체 범위. 저장 위치는 이름 일부로도 도구가 찾습니다. '+hint
        body['messages']=systems+[{'role':'system','content':state}]+recent
        # For a recognized writing request there is only one valid workflow.
        # Dispatch it on the server; do not ask the small router model whether
        # it feels like calling a tool (especially when file context is hidden).
        if allowed in ({'outline_write'},{'outline_read'},{'outline_edit'}) and body.get('tool_ids') and __user__ and __metadata__ and 'Tools' in globals():
            bridge=Tools()
            bridge.valves=bridge.Valves(AGENT_URL=self.valves.AGENT_URL,AGENT_TOKEN=self.valves.AGENT_TOKEN)
            if allowed=={'outline_edit'}:
                result=json.loads(await bridge._run('edit_request',{'request':raw},__user__,__metadata__,__event_emitter__))
            elif allowed=={'outline_read'}:
                result=json.loads(await bridge._run('read_request',{'request':raw},__user__,__metadata__,__event_emitter__))
            else:
                result=json.loads(await bridge.manage_outline_document(__messages__=messages,
                    __files__=body.get('files') or __metadata__.get('files'),__user__=__user__,__metadata__=__metadata__,__event_emitter__=__event_emitter__))
            __metadata__['outline_workflow_result']=result
            body.setdefault('metadata',{})['outline_workflow_result']=result
            body['tool_ids']=[]
            # The actual request and full result have already been handled.
            # Neither long history nor tool schemas are needed for this final ack.
            body['messages']=[{'role':'system','content':'서버 처리 결과는 최종 화면에 자동 표시됩니다. "처리 결과를 표시합니다." 한 문장만 답하세요.'},
                              {'role':'user','content':'처리 결과를 표시해 주세요.'}]
        return body

    async def outlet(self,body:dict,__user__:dict=None,__metadata__:dict=None,__event_emitter__=None)->dict:
        if body.get('model')!='outline-assistant': return body
        messages=body.get('messages',[])
        if not messages or messages[-1].get('role')!='assistant': return body
        m=messages[-1];results=[];fetch_failed=False
        direct=(__metadata__ or {}).get('outline_workflow_result') or body.get('metadata',{}).get('outline_workflow_result')
        if direct:
            try:
                full=await self.backend('result',body,__user__,__metadata__,{'event_id':direct['event_id']}) if direct.get('fetch_result') else direct
                if full:results.append(full)
            except Exception:fetch_failed=True
        for item in m.get('output',[]):
            if item.get('type')!='function_call_output': continue
            for v in item.get('output',[]):
                try:
                    d=json.loads(v.get('text',''))
                    if not isinstance(d,dict) or not d.get('status'): continue
                    if d.get('fetch_result'):
                        try:
                            full=await self.backend('result',body,__user__,__metadata__,{'event_id':d['event_id']})
                            if full: d=full
                            else: fetch_failed=True;continue
                        except Exception: fetch_failed=True;continue
                    results.append(d)
                except (ValueError,TypeError): pass
        successful=[r for r in results if r.get('status')=='succeeded']
        saved=[r for r in successful if r.get('verified') and r.get('url')]
        drafts=[r for r in successful if r.get('draft_id')]
        research=[r for r in successful if r.get('research_id')]
        pending=[r for r in results if r.get('status')=='needs_input' or r.get('needs_input')]
        failures=[r for r in results if r.get('status')=='failed']
        failed_candidates=[r for r in failures if isinstance(r.get('error'),dict) and r['error'].get('candidate')]
        content=None
        workflows=[r for r in results if r.get('workflow_id') and r.get('display')]
        interrupted=[r for r in results if r.get('status') in ('partial','cancelled','interrupted') and r.get('display')]
        if interrupted:
            content=interrupted[-1]['display']
        elif workflows:
            content=workflows[-1]['display']
        elif successful and (successful[-1].get('edit_result') or successful[-1].get('edit_preview')):
            content=successful[-1]['display']
        elif saved:
            r=saved[-1]
            content=('**기존 저장 결과 확인 · 중복 생성하지 않았습니다**' if r.get('duplicate') else '**Outline 저장·읽기 검증 완료**')+'\n\n'
            content+=f"[{r.get('title','문서 열기')}]({r['url']})"
            if r.get('location'): content+='\n\n저장 위치: '+r['location']
            if failed_candidates:
                content+='\n\n---\n후속 편집 초안은 검증을 통과하지 못했습니다. 위 저장본과 구분해 확인하세요.\n\n'+failure_text(failed_candidates[-1]['error'])
        elif failed_candidates:
            content=failure_text(failed_candidates[-1]['error'])
        elif pending:
            r=pending[-1];content=question_text(r.get('question') or r.get('error'))
            if r.get('draft_id'): content='**초안은 준비했습니다. 아직 저장하지 않았습니다.**\n\n'+r.get('markdown','')+'\n\n'+content
        elif drafts:
            r=drafts[-1];content='**초안 완료 · Outline에는 아직 저장하지 않았습니다**\n\n'+r['title']+'\n\n'+r['markdown']
            content+='\n\n수정할 부분을 말하거나 “시연 결과 아래에 저장해줘”처럼 위치를 알려주세요.'
            if failures: content+='\n\n후속 처리: '+question_text(failures[-1].get('error'))
        elif research:
            r=research[-1];content=r.get('display')
            if not content:
                content=r['report']+'\n\n### 조사 범위\n\n'+f"읽기 완료 {r['read_count']}개 / 관련 {r['matched_count']}개 · 실패/제외 {len(r.get('failed',[]))}개\n\n"+r.get('scope','')
                content+='\n\n### 출처\n\n'+'\n'.join(f"{i+1}. [{s['title']}]({s['url']})" for i,s in enumerate(r.get('sources',[])))
        elif failures: content=failure_text(failures[-1].get('error'))
        elif successful and successful[-1].get('display'): content=successful[-1]['display']
        elif fetch_failed: content='결과를 화면에 불러오지 못했습니다. 이 대화에서 “방금 결과 다시 보여줘”라고 요청해 주세요. 저장 작업을 새로 실행할 필요는 없습니다.'
        if content is not None:
            if direct:m['outline_workflow_result']=direct
            m['content']=content
            m['output']=[x for x in m.get('output',[]) if x.get('type')!='message']+[{'id':'outline-result-'+str(uuid.uuid4()),'type':'message','role':'assistant','status':'completed','content':[{'type':'output_text','text':content}]}]
            if __event_emitter__: await __event_emitter__({'type':'chat:completion','data':{'content':content,'output':m['output'],'done':True}})
        return body
