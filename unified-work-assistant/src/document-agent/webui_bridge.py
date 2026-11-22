"""Shared source used to register three reviewed Open WebUI workspace tool groups.
The installer appends the selected public methods to this Tools class.
"""
import asyncio
import base64
import json
from pathlib import Path
import httpx
from pydantic import BaseModel, Field


class Tools:
    class Valves(BaseModel):
        AGENT_URL: str = Field(default='http://document-agent:8000')
        AGENT_TOKEN: str = Field(default='', description='Local backend credential; never include in prompts')

    def __init__(self):
        self.valves = self.Valves()
        self.citation = False

    async def _identity_headers(self,user):
        if not user or not user.get('id') or not user.get('email'):raise ValueError('로그인 사용자 정보가 필요합니다.')
        from open_webui.models.users import Users
        account=await Users.get_user_by_id(user['id'])
        if not account or account.role not in ('user','admin') or account.email.lower()!=user['email'].lower():
            raise ValueError('활성 문서 비서 계정으로 다시 로그인하세요.')
        # Read the provider binding from WebUI's database, not tool arguments,
        # model output, or browser-supplied email/subject fields.
        subject=((account.oauth or {}).get('oidc') or {}).get('sub')
        if not isinstance(subject,str) or not subject:raise ValueError('문서 비서에 Authentik으로 로그인하세요.')
        async with httpx.AsyncClient(timeout=30) as client:
            response=await client.post('http://workhub:8000/internal/search/identity',
                headers={'X-Service-Token':self.valves.AGENT_TOKEN},
                json={'user_id':account.id,'email':account.email,'subject':subject})
            response.raise_for_status()
            return {'Authorization':'Bearer '+self.valves.AGENT_TOKEN,'X-Workhub-Identity':response.json()['token']}

    async def _checkpoint(self, content, done, user, metadata, emitter):
        output=[{'id':'outline-checkpoint','type':'message','role':'assistant',
            'status':'completed' if done else 'in_progress','content':[{'type':'output_text','text':content}]}]
        # Inlet emitters do not necessarily persist chat:completion events. Save the
        # same scoped assistant message so Stop/reload retains the completed work.
        if metadata.get('message_id'):
            try:
                from open_webui.models.chats import Chats
                chat=await Chats.get_chat_by_id(metadata['chat_id'])
                if chat and chat.user_id==user['id']:
                    await Chats.upsert_message_to_chat_by_id_and_message_id(metadata['chat_id'],metadata['message_id'],
                        {'content':content,'output':output,'done':done})
            except ImportError:
                pass  # Standalone bridge tests have no WebUI database.
        if emitter:await emitter({'type':'chat:completion','data':{'content':content,'output':output,'done':done}})

    async def _run(self, tool, arguments, user, metadata, emitter):
        if not metadata or not metadata.get('chat_id') or not user:
            return json.dumps({'status':'failed','error':'저장된 채팅에서 실행해 주세요.'}, ensure_ascii=False)
        labels={'read_request':'문서 탐색','catalog':'문서함과 양식 확인','read_document':'문서 읽기','research_documents':'관련 문서 조사','prepare_document':'메모 정리','save_document':'Outline 저장','ingest_attachment':'첨부 읽기','revise_document':'지정 문서 수정'}
        label=labels.get(tool,tool)
        if tool=='document_workflow':label='문서 작업'
        payload={'tool':tool,'arguments':arguments,'user_id':user['id'],'chat_id':metadata['chat_id'],'message_id':metadata.get('message_id','')}
        if emitter: await emitter({'type':'status','data':{'description':label+' 중','done':False}})
        event_id=None;last_display=None
        try:
            async with httpx.AsyncClient(timeout=1800) as client:
                headers=await self._identity_headers(user)
                r=await client.post(self.valves.AGENT_URL+'/agent/submit',headers=headers,json=payload)
                r.raise_for_status();result=r.json();event_id=result.get('event_id')
                scoped={**payload,'arguments':{'event_id':event_id}}
                while result.get('status') in ('queued','running'):
                    if emitter:
                        await emitter({'type':'status','data':{'description':result.get('progress',label+' 대기 중')+' · '+str(result.get('seconds',0))+'초','done':False}})
                        if result.get('display') and result['display']!=last_display:
                            last_display=result['display']
                            await self._checkpoint(last_display,False,user,metadata,emitter)
                    await asyncio.sleep(1)
                    r=await client.post(self.valves.AGENT_URL+'/agent/result',headers=headers,json=scoped,timeout=10)
                    r.raise_for_status();result=r.json()
        except asyncio.CancelledError:
            if event_id:
                async with httpx.AsyncClient(timeout=10) as client:
                    headers=await self._identity_headers(user)
                    await client.post(self.valves.AGENT_URL+'/agent/cancel',headers=headers,json={**payload,'arguments':{'event_id':event_id}})
                    if emitter:
                        for _ in range(20):
                            final=await client.post(self.valves.AGENT_URL+'/agent/result',headers=headers,json={**payload,'arguments':{'event_id':event_id}})
                            checkpoint=final.json()
                            if checkpoint.get('status') not in ('queued','running'):
                                if checkpoint.get('display'):await self._checkpoint(checkpoint['display'],True,user,metadata,emitter)
                                break
                            await asyncio.sleep(.1)
            raise
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code==401:
                result={'status':'failed','error':'문서 비서에 Authentik으로 다시 로그인하세요.'}
            elif exc.response.status_code==403:
                result={'status':'failed','error':'업무 서비스 계정 연결과 해당 Outline 컬렉션의 접근 권한을 확인하세요.'}
            elif exc.response.status_code==503:
                result={'status':'failed','error':'현재 계정·문서 권한을 확인하지 못했습니다. 잠시 후 다시 시도하세요.'}
            else:result={'status':'failed','error':'문서 서버 요청 실패: HTTP '+str(exc.response.status_code)}
        except ValueError as exc:
            result={'status':'failed','error':str(exc)}
        except Exception as exc:
            result={'status':'failed','error':'문서 서버 연결 오류: '+type(exc).__name__}
        if emitter:
            state={'succeeded':'완료','failed':'실패','partial':'부분 완료','cancelled':'중지됨','interrupted':'중단됨','needs_input':'위치 선택 필요'}.get(result.get('status'),'확인 필요')
            await emitter({'type':'status','data':{'description':label+' · '+state,'done':True}})
        # Full result stays on the server. The outlet fetches it by event ID and
        # chat/user scope; it must never consume the router's 4096-token context.
        if result.get('event_id') and tool!='ingest_attachment':
            keep=('event_id','status','workflow_id','research_id','draft_id','id','title','saved','verified','url','duplicate','location','read_count','matched_count','needs_input','revision','next_offset')
            result={k:result[k] for k in keep if k in result}
            result={k:(v[:200] if isinstance(v,str) else v) for k,v in result.items()}
            result['fetch_result']=True
            result['instruction']='본문은 완료 시 자동 표시됩니다. 성공이면 완료 여부만, 실패이면 미저장 초안을 표시한다고 한 문장으로 답하세요. 다른 도구를 반복 호출하지 마세요.'
            if tool=='read_document':
                result['instruction']='본문은 화면에 자동 표시됩니다. 사용자가 기존 문서 수정을 요청했다면 이 id로 revise_outline_document를 호출하세요. 수정 도구가 원문을 직접 읽습니다.'
        return json.dumps(result, ensure_ascii=False)
