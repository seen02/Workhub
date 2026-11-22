
    async def outline_catalog(self, collection_name: str = '', __user__: dict = None, __metadata__: dict = None, __event_emitter__=None) -> str:
        """저장 위치나 양식을 물었을 때만 목록 조회. 검색 전에는 필요 없습니다. collection_name은 생략하거나 이름 일부 사용 가능."""
        return await self._run('catalog', {'collection_name':collection_name}, __user__, __metadata__, __event_emitter__)

    async def read_outline_document(self, document_id: str, offset: int = 0, __messages__: list = None, __user__: dict = None, __metadata__: dict = None, __event_emitter__=None) -> str:
        """문서 제목 일부, ID 또는 링크로 본문을 읽습니다. 후보가 하나면 자동 선택. next_offset은 이어 읽을 위치."""
        import re
        raw=next((m.get('content','') for m in reversed(__messages__ or []) if m.get('role')=='user'),'')
        if isinstance(raw,list): raw='\n'.join(x.get('text','') for x in raw if x.get('type')=='text')
        if re.search(r'그\s*내용|방금.*(?:내용|결과)|위\s*내용|앞서.*(?:내용|결과)',raw) and not re.search(r'https?://|문서\s*(?:ID|아이디)',raw,re.I):
            return await self._run('research_documents', {'topic':'','instruction':raw}, __user__, __metadata__, __event_emitter__)
        return await self._run('read_document', {'document_id':document_id,'offset':offset}, __user__, __metadata__, __event_emitter__)

    async def research_outline(self, topic: str = '', collection_name: str = '', __messages__: list = None, __user__: dict = None, __metadata__: dict = None, __event_emitter__=None) -> str:
        """문서 조사. topic에는 프로젝트/검색어만. 컬렉션 생략=전체 검색. 후속 질문은 topic=''로 이전 조사 재사용. 최종 보고서·출처는 시스템이 표시하므로 다시 작성하지 마세요."""
        import re
        raw=next((m.get('content','') for m in reversed(__messages__ or []) if m.get('role')=='user'),'')
        if isinstance(raw,list): raw='\n'.join(x.get('text','') for x in raw if x.get('type')=='text')
        norm=lambda x:re.sub(r'[^\w]','',x.casefold())
        # A model-invented collection must never restrict the user's search.
        if collection_name and norm(collection_name) not in norm(raw): collection_name=''
        quoted=re.search(r'["“]([^"”]+)["”]\s*(?:관련|에\s*관한)',raw)
        if quoted: topic=quoted[1]
        elif topic and not all(norm(t) in norm(raw) for t in topic.split(',') if t.strip()):
            topic=''  # Follow-up: the backend resolves this chat's latest research.
        return await self._run('research_documents', {'topic':topic,'collection_name':collection_name,'instruction':raw,'mode':'all' if re.search(r'모두|전체|전부',raw) else 'quick','refresh':bool(re.search(r'최신|새로|다시\s*찾',raw))}, __user__, __metadata__, __event_emitter__)
