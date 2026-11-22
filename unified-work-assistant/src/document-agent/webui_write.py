
    async def prepare_outline_draft(self, text: str = '', instruction: str = '', template_name: str = '', file_id: str = '', title: str = '', preserve_original: bool = False, collection_name: str = '', parent_title: str = '', __messages__: list = None, __user__: dict = None, __metadata__: dict = None, __event_emitter__=None) -> str:
        """메모/첨부를 정리하고 실제 템플릿 적용. 사용자가 저장을 요청했다면 collection_name과 parent_title을 함께 넣으면 정리+저장+확인까지 실행. 저장 요청 없으면 collection_name은 빈 문자열. 이름은 일부만 가능하며 저장은 parent_title만으로도 위치를 찾습니다. text/file_id 둘 다 비우면 이전 초안을 instruction대로 수정. 원문 그대로는 preserve_original=true."""
        # Protect explicitly labelled source and quoted targets from router omissions.
        import re
        raw=next((m.get('content','') for m in reversed(__messages__ or []) if m.get('role')=='user'),'')
        if isinstance(raw,list): raw='\n'.join(x.get('text','') for x in raw if x.get('type')=='text')
        source=re.search(r'(?:메모(?:\s*원문)?|원문)\s*[:：]\s*([\s\S]+)$',raw)
        if source and not file_id: text=source.group(1).strip()
        request_text=raw[:source.start()] if source else raw
        def quoted(suffix):
            matches=re.findall(r'["“]([^"”]+)["”]\s*'+suffix,raw)
            return matches[0] if len(matches)==1 else ''
        title=quoted('제목') or quoted('(?:으)?로\\s*바(?:꿔|꾸)') or title
        template_name=quoted('(?:템플릿|양식)') or template_name
        named_form=re.search(r'(?:메모를|내용을|원문을|아래\s*메모를)\s+([^\n.!?]+?(?:양식|템플릿))\s*(?:에\s*맞|형태로)',request_text)
        if named_form: template_name=named_form[1].strip(' "“”')
        if not re.search(r'템플릿|양식',request_text): template_name=''
        preserve_original=bool(re.search(r'(?:원문|내용|초안).*?그대로|수정\s*없이',request_text))
        use_attachment=not file_id and bool(re.search(r'첨부(?:한|된|\s*문서|\s*파일)',request_text))
        if re.search(r'저장(?:하지\s*마|하지\s*말|\s*금지)',request_text): collection_name=''
        elif re.search(r'저장|넣어|등록',request_text):
            collection_name=quoted('컬렉션') or collection_name
        save_requested=bool(re.search(r'저장|넣어|등록',request_text)) and not bool(re.search(r'저장(?:하지\s*마|하지\s*말|\s*금지)|아직.*저장.*마',request_text))
        if not save_requested: collection_name='';parent_title=''
        if save_requested:
            collection_name=quoted('컬렉션') or collection_name
            parent_title=self._parent_from_request(request_text) or quoted('(?:아래|하위)') or parent_title
        if not source and not file_id and re.search(r'(?:방금|이전|이)\s*(?:만든\s*)?초안.*그대로',request_text) and save_requested:
            return await self._run('save_document', {'draft_id':'latest','collection_name':collection_name,'parent_title':parent_title,'title':title}, __user__, __metadata__, __event_emitter__)
        if not source and not file_id and re.search(r'(?:방금|이전)\s*초안',request_text): text=''
        instruction=request_text or instruction
        return await self._run('prepare_document', {'text':text,'instruction':instruction,'template_name':template_name,'file_id':file_id,'use_latest_attachment':use_attachment,'title':title,'preserve_original':preserve_original,'save_requested':save_requested,'collection_name':collection_name,'parent_title':parent_title}, __user__, __metadata__, __event_emitter__)

    async def save_outline_draft(self, collection_name: str = '', parent_title: str = '', draft_id: str = 'latest', title: str = '', __messages__: list = None, __user__: dict = None, __metadata__: dict = None, __event_emitter__=None) -> str:
        """사용자가 저장/넣어줘 요청한 초안을 지정 위치에 그대로 저장. 이름 일부 허용. parent_title만 주면 컬렉션 자동 탐색. 위치 생략 시 이 대화의 이전 위치 재사용. 준비된 draft_id 또는 latest. parent_title을 비우면 컬렉션 최상위. 사용자 요청 없는 저장 금지. 반환 verified/url 확인 후 완료 보고."""
        import re
        raw=next((m.get('content','') for m in reversed(__messages__ or []) if m.get('role')=='user'),'')
        if isinstance(raw,list): raw='\n'.join(x.get('text','') for x in raw if x.get('type')=='text')
        reuse=bool(re.search(r'(?:같은|동일한|동일)\s*위치',raw))
        if reuse: draft_id='latest'
        if not reuse: parent_title=self._parent_from_request(raw) or parent_title
        return await self._run('save_document', {'collection_name':collection_name,'parent_title':parent_title,'draft_id':draft_id,'title':title,'reuse_last_destination':reuse}, __user__, __metadata__, __event_emitter__)

    def _parent_from_request(self, raw):
        import re
        quoted=re.search(r'["“]([^"”]+)["”]\s*(?:아래|하위)',raw)
        if quoted:return quoted[1]
        match=re.search(r'([^\n.!?]+?)\s*(?:아래|하위)(?:에)?',raw)
        if not match:return ''
        text=re.split(r'컬렉션의\s*|문서함의\s*|초안을\s*|문서를\s*|메모를\s*|회의록을\s*',match[1])[-1]
        text=re.sub(r'^(?:(?:원문|내용)\s*)*(?:그대로|정리해서|다듬어서)\s*','',text.strip())
        return text.strip(' "“”')

    async def revise_outline_document(self, document_id: str, instruction: str, __user__: dict = None, __metadata__: dict = None, __event_emitter__=None) -> str:
        """사용자가 지정한 기존 문서의 한 부분을 수정합니다. 4000자 이하 문서, 한 번에 한 곳 치환. read_outline_document로 먼저 확인하고 명시적으로 수정 요청한 경우만 실행."""
        return await self._run('revise_document', {'document_id':document_id,'instruction':instruction}, __user__, __metadata__, __event_emitter__)
