"""Scoped search-result selection and revision-bound edit previews."""
import json
import re
from fastapi import HTTPException
from agent_ux import candidates


class EditWorkflow:
    def __init__(self, db, core, pages):
        self.db,self.core,self.pages=db,core,pages
        db.execute('CREATE TABLE IF NOT EXISTS edit_previews(scope TEXT PRIMARY KEY,plan TEXT,result TEXT)')
        db.commit()

    def pending(self, scope):
        row=self.db.execute('SELECT plan,result FROM edit_previews WHERE scope=?',(scope,)).fetchone()
        return json.loads(row['plan']) if row and not row['result'] else None

    async def __call__(self,a,req):
        raw=a.get('request','').strip();scope=req.user_id+':'+req.chat_id
        confirm=bool(re.fullmatch(r'(?:변경|수정)?\s*(?:내용을?\s*)?(?:적용|확정|저장)(?:해줘|해\s*줘|해주세요|할게)?[.!\s]*',raw))
        row=self.db.execute('SELECT plan,result FROM edit_previews WHERE scope=?',(scope,)).fetchone()
        if confirm:
            if not row:raise HTTPException(409,'이 대화에 적용할 수정 미리보기가 없습니다.')
            plan=json.loads(row['plan'])
            if row['result']:
                doc=await self.core.info(plan['id'])
                if self.core.normalize(doc['text'])!=self.core.normalize(plan['after']):raise HTTPException(409,'문서가 다시 변경되었습니다. 새 수정 요청이 필요합니다.')
                return {**json.loads(row['result']),'duplicate':True}
        else:
            if not re.search(r'바꿔|바꾸|수정|변경|교체',raw):raise HTTPException(422,'변경할 내용을 알려주세요.')
            url=re.search(r'https?://[^\s<>\"”’]+/doc/[^\s<>\"”’]+',raw)
            if url:doc=await self.core.info(self.core.extract_id(url[0].rstrip('.。,')))
            else:
                research=self.db.execute('SELECT result FROM research WHERE scope=? ORDER BY created DESC LIMIT 1',(scope,)).fetchone()
                sources=json.loads(research['result']).get('sources',[]) if research else []
                number=re.search(r'(?:검색\s*결과\s*)?(\d+)\s*번\s*(?:문서|자료|결과)',raw)
                if number:matches=[s for s in sources if s.get('number')==int(number[1])]
                elif re.search(r'이\s*문서|그\s*문서|방금.*문서',raw):matches=sources
                else:
                    name=re.search(r'[\"“‘\']([^\"”’\']+)[\"”’\']\s*문서',raw)
                    docs,_=await self.pages('documents.list')
                    matches=candidates(docs,name[1]) if name else []
                if len(matches)!=1:
                    return {'status':'needs_input','display':'수정할 문서를 지정해 주세요. 검색 결과 번호와 함께 “1번 문서에서 …” 또는 문서 링크를 사용하세요.',
                            'question':{'message':'수정할 문서를 지정해 주세요.','candidates':[{'id':s['id'],'title':s['title']} for s in matches]}}
                doc=await self.core.info(matches[0]['id'])
            if doc.get('archivedAt') or doc.get('deletedAt'):raise HTTPException(409,'보관되거나 삭제된 문서는 수정하지 않습니다.')
            pair=re.search(r'[\"“‘\']([^\"”’\']+)[\"”’\']\s*(?:을|를)\s*[\"“‘\']([^\"”’\']+)[\"”’\']\s*(?:으)?로',raw)
            if not pair:raise HTTPException(409,'바꿀 원문과 새 구절을 따옴표로 지정해 주세요. 예: ‘김민수 담당자’를 ‘이서연 담당자’로 바꿔줘.')
            old,new=pair[1],pair[2];text=doc.get('text','')
            if len(text)>4000:raise HTTPException(422,'현재 수정 기능은 4000자 이하 문서를 지원합니다.')
            editable=text.split('## 입력 원문')[0]
            if text.count(old)!=1 or editable.count(old)!=1:raise HTTPException(409,'바꿀 구절이 원문에서 유일하지 않습니다. 문장 전체를 지정해 주세요.')
            if doc.get('revision') is None:raise HTTPException(409,'문서 버전을 확인할 수 없습니다.')
            plan={'id':doc['id'],'title':doc['title'],'url':self.core.doc_result(doc)['url'],'before':text,'after':text.replace(old,new,1),
                  'old':old,'new':new,'revision':doc['revision'],'updatedAt':doc.get('updatedAt')}
            self.db.execute('INSERT OR REPLACE INTO edit_previews VALUES (?,?,NULL)',(scope,json.dumps(plan,ensure_ascii=False)));self.db.commit()
            if re.search(r'미리|저장하지|적용하지|바꾸기\s*전|변경\s*전후.*보여',raw):
                return {'status':'succeeded','edit_preview':True,'id':doc['id'],'display':self.display(plan,False)}
        current=await self.core.info(plan['id'])
        if self.core.normalize(current['text'])!=self.core.normalize(plan['after']):
            if current['text']!=plan['before'] or current.get('revision')!=plan['revision'] or current.get('updatedAt')!=plan['updatedAt']:
                raise HTTPException(409,'미리보기 이후 문서가 변경되었습니다. 최신 문서로 다시 요청해 주세요.')
            await self.core.outline('documents.update',{'id':plan['id'],'editMode':'patch','findText':plan['old'],'text':plan['new'],'lastRevision':plan['revision']})
            current=await self.core.info(plan['id'])
        if self.core.normalize(current['text'])!=self.core.normalize(plan['after']):raise HTTPException(503,'수정 결과를 확인하지 못했습니다. 같은 미리보기에서 적용을 재시도하세요.')
        result={**self.core.doc_result(current),'status':'succeeded','edit_result':True,'patch':{'before':plan['old'],'after':plan['new']},'display':self.display(plan,True)}
        self.db.execute('UPDATE edit_previews SET result=? WHERE scope=?',(json.dumps(result,ensure_ascii=False),scope));self.db.commit()
        return result

    def display(self,plan,saved):
        return ('**수정·읽기 확인 완료**' if saved else '**수정 미리보기 · 아직 저장하지 않았습니다**')+f"\n\n[{plan['title']}]({plan['url']})\n\n변경 전: {plan['old']}\n\n변경 후: {plan['new']}"+('' if saved else '\n\n같은 채팅에서 “적용해줘”라고 하면 이 변경만 저장합니다.')
