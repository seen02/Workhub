
    async def manage_outline_document(self, request: str = '', __messages__: list = None, __files__: list = None, __user__: dict = None, __metadata__: dict = None, __event_emitter__=None) -> str:
        """메모/첨부 정리, 템플릿 적용, 초안 수정, 저장, 없으면 상위 문서 생성, 선택 번호 답변, 실패 재시도. 사용자 요청 전체를 전달하면 서버가 이전 작업부터 이어서 처리합니다. 이 도구 한 번으로 완료하며 결과 본문은 자동 표시됩니다."""
        raw=next((m.get('content','') for m in reversed(__messages__ or []) if m.get('role')=='user'),request)
        if isinstance(raw,list):raw='\n'.join(x.get('text','') for x in raw if x.get('type')=='text')
        args={'request':raw}
        if __files__:
            uploaded=json.loads(await self._read_outline_attachment(__files__=__files__,__user__=__user__,__metadata__=__metadata__,__event_emitter__=__event_emitter__))
            if uploaded.get('status')!='succeeded':return json.dumps(uploaded,ensure_ascii=False)
            args['file_id']=uploaded['file_id']
        return await self._run('document_workflow',args,__user__,__metadata__,__event_emitter__)

