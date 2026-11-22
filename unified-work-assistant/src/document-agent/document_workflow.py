"""Durable, scoped document workflow. LLM interprets text; server owns execution."""
import json
import asyncio
import re
import time
import uuid
from fastapi import HTTPException
from agent_ux import candidates, normalized


def dump(value):
    return json.dumps(value, ensure_ascii=False)


class DocumentWorkflow:
    def __init__(self, conn, core, prepare, save, pages, progress):
        self.db, self.core = conn, core
        self.prepare, self.save, self.pages, self.progress = prepare, save, pages, progress
        conn.executescript('''
          CREATE TABLE IF NOT EXISTS workflow_tasks(id TEXT PRIMARY KEY,scope TEXT,state TEXT,updated REAL);
          CREATE TABLE IF NOT EXISTS workflow_requests(scope TEXT,message TEXT,result TEXT,PRIMARY KEY(scope,message));
        ''')
        conn.commit()
        for row in conn.execute('SELECT id,state FROM workflow_tasks').fetchall():
            state=json.loads(row['state'])
            if state.get('status')=='running':
                state.update(status='interrupted',error='서버 재시작으로 중단되었습니다. 같은 초안으로 재시도하면 기존 저장 UUID를 먼저 확인합니다.')
                conn.execute('UPDATE workflow_tasks SET state=? WHERE id=?',(dump(state),row['id']))
        conn.commit()

    def scope(self, req):
        return req.user_id + ':' + req.chat_id

    def latest(self, req):
        row = self.db.execute('SELECT state FROM workflow_tasks WHERE scope=? ORDER BY updated DESC LIMIT 1', (self.scope(req),)).fetchone()
        return json.loads(row['state']) if row else None

    def put(self, task, req):
        self.db.execute('INSERT OR REPLACE INTO workflow_tasks VALUES (?,?,?,?)', (task['id'], self.scope(req), dump(task), time.time()))
        self.db.commit()
        runtime=getattr(self.core.app.state,'task_runtime',None)
        if runtime:runtime.update(**self.render(task,req))

    def context(self, req):
        t = self.latest(req)
        if not t: return {}
        return {'task_id':t['id'], 'status':t.get('status'), 'step':t.get('step'),
                'draft_id':t.get('draft_id'), 'choices':[{'number':i,'title':(x.get('name') or x.get('title',''))[:80]} for i,x in enumerate(t.get('choices', []),1)], 'question':t.get('question', '')[:160],
                'collection':t['spec'].get('collection'), 'parent':t['spec'].get('parent')}

    def draft(self, task, req):
        return self.db.execute('SELECT * FROM drafts WHERE id=? AND scope=?', (task.get('draft_id') or task.get('previous_draft_id'), self.scope(req))).fetchone()

    def render(self, task, req):
        d = self.draft(task, req)
        result = dict(task.get('saved_result') or {})
        result.update(workflow_id=task['id'], status=task.get('status', 'succeeded'), step=task.get('step'),
                      draft_id=task.get('draft_id'), saved=bool(task.get('saved_result')), needs_input=task.get('status')=='needs_input')
        if d: result.update(title=d['title'], markdown=d['body'])
        if task.get('saved_result'):
            r = task['saved_result']
            text = '**Outline 저장·읽기 확인 완료**\n\n'+f"[{r['title']}]({r['url']})\n\n저장 위치: {r.get('location','')}"
            if r.get('duplicate'): text += '\n\n기존 저장 결과를 확인했습니다. 중복 생성하지 않았습니다.'
        else:
            text = '**'+({'failed':'작업 중단 · 초안과 진행 상태를 보관했습니다','cancelled':'작업 취소 · 초안을 보관했습니다','interrupted':'작업 중단 · 초안을 보관했습니다','running':'작업 진행 중', 'needs_input':'선택 대기 · 아직 저장하지 않았습니다'}.get(task.get('status'), '초안 완료 · 아직 저장하지 않았습니다'))+'**'
        if d:
            if not task.get('draft_id'):text+='\n\n새 버전 생성에 실패하여 이전 초안을 표시합니다.'
            text += '\n\n### '+d['title']+'\n\n'+d['body']
        if task.get('error'):
            err = task['error']
            text += '\n\n### 확인할 부분\n\n'+str(err.get('message',err) if isinstance(err,dict) else err)
            if isinstance(err,dict):
                for issue in err.get('issues',[]): text += '\n- '+str(issue)
                for key,label in [('missing_numbers','누락 숫자'),('extra_numbers','추가 숫자')]:
                    if err.get(key): text += '\n- '+label+': '+', '.join(err[key])
                if err.get('partial'): text += f"\n- 원문 {err['total_parts']}부분 중 {err['processed_parts']}부분까지 처리했습니다."
        if task.get('warnings'):
            text += '\n\n<details>\n<summary>자동 검토 참고 '+str(len(task['warnings']))+'건 · 모델 오판 가능</summary>\n\n'+'\n\n'.join(task['warnings'])+'\n\n</details>'
        if task.get('choices'):
            text += '\n\n'+task.get('question','어느 항목을 사용할까요?')+'\n\n'
            text += '\n'.join(f"{i}. {x.get('path') or x.get('name') or x.get('title')}" for i,x in enumerate(task['choices'],1))
            text += '\n\n번호나 이름으로 답하면 이어서 처리합니다.'
            result['question']={'message':task.get('question'), 'candidates':task['choices']}
        elif not task.get('saved_result'):
            if task.get('step')=='validate': text += '\n\n“초안을 다시 다듬어줘”로 새 버전을 만들 수 있습니다. 이 검증 실패 버전은 저장되지 않습니다.'
            elif task.get('status')=='failed': text += '\n\n“다시 시도해줘”로 중단한 단계부터 이어갈 수 있습니다.'
            elif task.get('question'): text += '\n\n'+task['question']
            else: text += '\n\n수정할 내용을 말하거나 저장 위치를 알려주세요.'
        if task.get('parent_created'): text += '\n\n상위 문서 생성 완료: '+task['spec'].get('parent','')
        result['display']=text
        return result

    async def interpret(self, raw, task):
        marker = re.search(r'(?:메모(?:\s*원문)?|원문)\s*[:：]', raw)
        request, source = (raw[:marker.start()], raw[marker.end():].strip()) if marker else (raw, '')
        props = {k:{'type':'string'} for k in ('collection','parent','template','title','source','replace_old','replace_new')}
        props.update(action={'type':'string','enum':['compose','edit','save','show','retry']},
                     save_requested={'type':'boolean'},create_parent={'type':'boolean'},preserve_original={'type':'boolean'})
        schema={'type':'object','properties':props,'required':list(props),'additionalProperties':False}
        spec,_ = await self.core.llm(
            '문서 작업 요청을 JSON으로 해석하세요. 실행하지 마세요. collection은 문서함 이름, parent는 상위 문서 제목, template은 양식 이름. '
            '조사/접미사(컬렉션, 문서, 아래에)와 괄호 조건을 이름에 붙이지 마세요. 모르는 값은 빈 문자열. '
            '새 메모는 compose. 이전 초안을 고치면 edit. 이미 만든 초안을 그대로 저장하면 save. 다시 보여달라면 show. 재시도는 retry. '
            '없으면 만들어라는 상위 문서 생성 지시가 있을 때만 create_parent=true. 명시적으로 저장/넣어달라는 요청이면 save_requested=true. 저장하지 말라면 false. '
            '원문 그대로 옮길 때만 preserve_original=true. source에는 요청 안에 있는 메모 원문을 그대로 복사하거나 빈 문자열. '
            '초안의 사실 변경을 명시한 경우에만 replace_old에 원문에서 바꿀 정확한 구절, replace_new에 사용자가 준 새 구절을 넣으세요. '
            '문체 교정은 replace_old와 replace_new 둘 다 빈 문자열. 이름이나 숫자를 예시로 지어내지 마세요. '
            '상위 문서 이름을 새 문서 title로 쓰지 마세요. 제목을 명시하지 않으면 title은 빈 문자열.',
            dump({'요청':request, '새원문있음':bool(source), '이전작업':{k:(v[:1000] if k=='source' else v) for k,v in task['spec'].items() if k not in ('instruction','file_id')} if task else None}),schema,650)
        # Never accept a model-invented source. Preserve marked source verbatim.
        if source: spec['source']=source;spec['action']='compose'
        elif spec['source'] and spec['source'] not in raw: spec['source']=''
        spec['instruction']=request
        if re.search(r'간단\s*업무\s*보고\s*(?:양식|템플릿)',request):spec['template']='간단 업무 보고 양식'
        # Ground names in the user's command, never in prompt examples or source.
        quoted=re.findall(r'''["“‘']([^"”’']+)["”’']\s*(컬렉션|문서함|템플릿|양식|문서\s*(?:\([^)]*\))?\s*(?:아래|하위)|아래|하위)''',request)
        for name,kind in quoted:
            field='collection' if kind in ('컬렉션','문서함') else 'template' if kind in ('템플릿','양식') else 'parent'
            spec[field]=name
        for field in ('collection','parent','template'):
            value=normalized(spec.get(field,''))
            if value and value not in normalized(request) and (not task or spec[field]!=task['spec'].get(field)):
                spec[field]=''
        # Ground destination against the current catalogue just like read requests.
        # A model-added suffix such as "컬렉션" must not trigger needless choices.
        from request_intent import interpret_read
        collections,_=await self.pages('collections.list')
        explicit=interpret_read(request,collections).get('collection_name','')
        if explicit and any(c['name']==explicit for c in collections):spec['collection']=explicit
        title_match=re.search(r'[\"“‘\']([^\"”’\']+)[\"”’\']\s*(?:라는\s*)?제목',request)
        if not title_match:title_match=re.search(r'제목[은을:]?\s*[\"“‘\']([^\"”’\']+)[\"”’\']',request)
        if title_match:spec['title']=title_match[1]
        if '제목' not in request:spec['title']=''
        save_verb=bool(re.search(r'저장|넣어|등록|올려',request))
        no_save=bool(re.search(r'저장하지|저장\s*금지|저장.*(?:마[.\s]|마$|말)',request))
        spec['save_requested']=save_verb and not no_save
        spec['create_parent']=bool(re.search(r'없(?:으|다)면|없을\s*경우',request) and re.search(r'만들|생성',request))
        if task and spec['create_parent'] and not no_save and task.get('status')=='needs_input':
            spec['save_requested']=task['spec'].get('save_requested',False)
            spec['action']='retry'
        if task and not source and re.search(r'바꿔|바꾸|수정해|수정하|변경해|다듬어|고쳐|고치',request):
            spec['action']='edit'
            replacement=re.search(r'(\d+(?:[:.]\d+)?(?:시|분|일|초|개|명|%)?)\s*(?:을|를)\s*(\d+(?:[:.]\d+)?(?:시|분|일|초|개|명|%)?)\s*(?:으)?로\s*(?:바꿔|바꾸|변경)',request)
            if replacement:spec.update(replace_old=replacement[1],replace_new=replacement[2])
        return spec

    def pending(self, task, field, rows, question, req):
        task.update(status='needs_input', choices=rows[:12], choice_field=field, question=question)
        self.put(task,req)

    async def resolve(self, task, req, field, rows, namefield='title'):
        key=field+'_id'
        if task['spec'].get(key):
            found=[r for r in rows if r['id']==task['spec'][key]]
            if found:return found[0]
            task['spec'].pop(key,None)
        query=task['spec'].get(field,'')
        found=candidates(rows,query,namefield) if query else rows
        if len(found)==1:
            task['spec'][key]=found[0]['id'];task['spec'][field]=found[0].get(namefield,query)
            self.put(task,req);return found[0]
        if field=='parent' and query and not found and task['spec'].get('create_parent'): return None
        self.pending(task,field,found or rows, f'“{query}” 후보를 하나로 정하지 못했습니다. 사용할 항목을 골라주세요.' if query else '저장할 문서함을 골라주세요.',req)
        if not found and field=='parent':
            task['question']=f'“{query}” 문서가 없습니다. “없으면 만들어서 저장해줘”라고 하거나 다른 위치를 알려주세요.'
            self.put(task,req)
        return False

    async def parent_create(self, task, req, col):
        s=task['spec'];fingerprint=self.core.digest({'collection':col['id'],'parent':normalized(s['parent'])})
        key='workflow-parent:'+fingerprint
        plan,result=self.core.job(key,fingerprint)
        if not plan:
            plan={'id':str(uuid.uuid4()),'title':s['parent'],'text':'','collectionId':col['id'],'publish':True}
            self.core.put_job(key,fingerprint,'workflow-parent',plan)
        doc=await self.core.verify_create(plan)
        if not doc:
            try: await self.core.outline('documents.create',plan)
            except HTTPException as e:
                if e.status_code<500 and e.status_code not in (409,429):raise
            doc=await self.core.verify_create(plan)
        if not doc:raise HTTPException(503,'상위 문서 생성 결과를 확인하지 못했습니다. 같은 작업으로 재시도하면 기존 UUID부터 확인합니다.')
        self.core.put_job(key,fingerprint,'workflow-parent',plan,self.core.doc_result(doc))
        task['parent_created']=True;s['parent_id']=doc['id'];self.put(task,req)
        return doc

    async def run(self, task, req):
        s=task['spec'];task.update(status='running', error=None, question='', choices=[])
        task.pop('saved_result',None)
        self.put(task,req)
        try:
            if not task.get('draft_id'):
                task['step']='draft';self.put(task,req);self.progress(req,'원문으로 초안 작성·검증 중')
                # Resolve template once and remember the displayed candidates.
                if s.get('template') and not s.get('template_id'):
                    templates,_=await self.pages('templates.list')
                    from template_layout import compact_template
                    if compact_template(s['template']):templates=[compact_template(s['template'])]+templates
                    # Prefer registered templates over reports written from them.
                    # "업무 보고" should not compete with every saved 업무 보고.
                    clean=lambda value:re.sub(r'(?:템플릿|양식)$','',normalized(value))
                    exact=[r for r in templates if clean(r['title'])==clean(s['template'])]
                    rows=exact or candidates(templates,s['template'])
                    if not rows:
                        docs,_=await self.pages('documents.list')
                        rows=docs
                    chosen=await self.resolve(task,req,'template',rows)
                    if chosen is False:return self.render(task,req)
                draft=await self.prepare({'text':s.get('source',''), 'file_id':s.get('file_id',''),
                    'instruction':s.get('instruction',''), 'template_name':s.get('template_id') or s.get('template',''),
                    'title':s.get('title',''),'preserve_original':s.get('preserve_original',False),
                    'workflow_version':task.get('version',1)},req)
                task['draft_id']=draft['draft_id'];task['warnings']=draft.get('missing_information',[])
                record=self.draft(task,req)
                if record:s['source']=record['source'];s.pop('file_id',None)
                self.put(task,req)
            if not s.get('save_requested'):
                task.update(status='succeeded',step='preview');self.put(task,req);return self.render(task,req)
            # Validation gate runs before creating a parent or writing any document.
            validation=self.db.execute('SELECT state FROM draft_validation WHERE draft_id=?',(task['draft_id'],)).fetchone()
            if validation and validation['state']=='blocked':raise HTTPException(422,'이 버전은 검증을 통과하지 못했습니다. 먼저 초안을 수정해 주세요.')
            task['step']='destination';self.put(task,req);self.progress(req,'저장 위치 확인 중')
            cols,_=await self.pages('collections.list')
            if not s.get('collection') and s.get('parent'):
                docs,_=await self.pages('documents.list');matches=candidates(docs,s['parent'])
                if len(matches)==1:s['collection_id']=matches[0]['collectionId'];s['parent_id']=matches[0]['id']
            col=await self.resolve(task,req,'collection',cols,'name')
            if col is False:return self.render(task,req)
            parent=None
            if s.get('parent'):
                docs,complete=await self.pages('documents.list',{'collectionId':col['id']})
                parent=await self.resolve(task,req,'parent',docs)
                if parent is False:return self.render(task,req)
                if parent is None:
                    if not complete:raise HTTPException(409,'문서 목록을 모두 읽지 못해 없는 문서인지 확정할 수 없습니다.')
                    task['step']='create_parent';self.put(task,req);self.progress(req,'요청한 상위 문서 생성·확인 중')
                    parent=await self.parent_create(task,req,col)
            task['step']='save';self.put(task,req);self.progress(req,'초안 저장 후 원문·위치 확인 중')
            result=await self.save({'draft_id':task['draft_id'],'collection_name':col['id'],
                                    'parent_title':parent['id'] if parent else '', 'title':s.get('title','')},req)
            task.update(saved_result=result,status='succeeded',step='done');self.put(task,req)
        except asyncio.CancelledError:
            task.update(status='cancelled',error='작업을 중지했습니다. 저장 요청이 전송되었다면 재시도할 때 같은 UUID로 저장 여부를 먼저 확인합니다.')
            self.put(task,req)
            raise
        except HTTPException as e:
            error=e.detail
            if isinstance(error,dict) and error.get('draft_id'):
                task['draft_id']=error['draft_id'];task['step']='validate'
            task.update(status='failed',error=error);self.put(task,req)
        except Exception as e:
            task.update(status='failed',error='처리 중 오류가 발생했습니다 ('+type(e).__name__+'). 진행 상태는 보관했습니다.');self.put(task,req)
        return self.render(task,req)

    async def __call__(self, a, req):
        raw=a.get('request','').strip()
        if not raw:raise HTTPException(422,'사용자 요청이 비어 있습니다.')
        cachekey=(req.message_id+':'+self.core.digest(raw)) if req.message_id else ''
        if cachekey:
            old=self.db.execute('SELECT result FROM workflow_requests WHERE scope=? AND message=?',(self.scope(req),cachekey)).fetchone()
            if old:return json.loads(old['result'])
        t=self.latest(req)
        # Adopt an existing scoped preview so pre-upgrade conversations still work.
        if not t:
            d=self.db.execute('SELECT * FROM drafts WHERE scope=? ORDER BY created DESC LIMIT 1',(self.scope(req),)).fetchone()
            if d:
                t={'id':str(uuid.uuid4()),'spec':{'source':d['source'],'title':d['title'],'save_requested':False},'draft_id':d['id'],'step':'preview','status':'succeeded'}
                dest=self.db.execute('SELECT * FROM draft_destinations WHERE draft_id=?',(d['id'],)).fetchone()
                if dest:t['spec'].update(collection=dest['collection_id'],parent=dest['parent_id'])
        number=re.fullmatch(r'\s*(\d+)\s*번?(?:이야|이요|으로|에|을|를)?(?:\s*(?:선택|저장)(?:해줘|해주세요)?)?[.!\s]*',raw)
        if t and t.get('choices') and (number or any(normalized(raw)==normalized(x.get('name') or x.get('title','')) for x in t['choices'])):
            choices=t['choices'];index=int(number[1])-1 if number else next(i for i,x in enumerate(choices) if normalized(raw)==normalized(x.get('name') or x.get('title','')))
            if 0<=index<len(choices):
                field=t['choice_field'];chosen=choices[index];t['spec'][field+'_id']=chosen['id'];t['spec'][field]=chosen.get('name') or chosen.get('title')
                result=await self.run(t,req)
            else:result=self.render(t,req)
        elif t and re.fullmatch(r'(?:방금\s*)?(?:결과|초안)(?:을)?\s*(?:다시\s*)?보여(?:줘|주세요)[.!\s]*',raw):
            result=self.render(t,req)
        elif t and re.fullmatch(r'(?:저장만\s*)?(?:다시\s*(?:시도|저장)|재시도)(?:해줘|해주세요)?[.!\s]*',raw):
            if t.get('step')=='validate':
                t.pop('draft_id',None);t['version']=t.get('version',1)+1
            result=await self.run(t,req)
        else:
            spec=await self.interpret(raw,t)
            action=spec.pop('action')
            if action=='show' and t:result=self.render(t,req)
            else:
                if not t or action=='compose':
                    t={'id':str(uuid.uuid4()),'spec':spec,'version':1}
                else:
                    spec.pop('source',None)
                    # New locations invalidate resolved IDs; absent names retain scope.
                    for field in ('collection','parent','template'):
                        if spec.get(field) and spec[field]!=t['spec'].get(field):t['spec'].pop(field+'_id',None)
                    retained={k:v for k,v in spec.items() if v or k=='save_requested'}
                    if action=='retry':retained['save_requested']=t['spec'].get('save_requested',False)
                    t['spec'].update(retained)
                    if action=='edit':
                        t['spec']['preserve_original']=spec.get('preserve_original',False)
                        old,new=spec.get('replace_old'),spec.get('replace_new')
                        source=t['spec'].get('source','')
                        if old and new:
                            if source.count(old)!=1 or new not in raw:
                                raise HTTPException(409,'바꿀 원문 구절을 하나로 정하지 못했습니다. 바꿀 구절과 새 구절을 함께 적어주세요.')
                            t['spec']['source']=source.replace(old,new,1)
                        t.setdefault('versions',[]).append(t.get('draft_id'))
                        t['previous_draft_id']=t.get('draft_id')
                        t.pop('draft_id',None);t.pop('saved_result',None);t['version']=t.get('version',1)+1
                    if action=='save':t['spec']['save_requested']=spec['save_requested']
                    if action=='retry' and t.get('step')=='validate':t.pop('draft_id',None);t['version']=t.get('version',1)+1
                if a.get('file_id'):t['spec']['file_id']=a['file_id']
                if not t.get('draft_id') and not t['spec'].get('source') and not t['spec'].get('file_id'):
                    t.update(status='needs_input',step='source',question='정리할 메모를 적거나 파일을 첨부해 주세요.')
                    self.put(t,req);result=self.render(t,req)
                else:result=await self.run(t,req)
        if cachekey:
            self.db.execute('INSERT OR REPLACE INTO workflow_requests VALUES (?,?,?)',(self.scope(req),cachekey,dump(result)));self.db.commit()
        return result
