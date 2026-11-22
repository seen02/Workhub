
    async def revise_outline_document(self, document_id: str, instruction: str, __user__: dict = None, __metadata__: dict = None, __event_emitter__=None) -> str:
        """이미 Outline에 저장된 문서의 한 부분 수정. 먼저 read_outline_document로 읽은 실제 ID 사용. 4000자 이하 문서만 지원."""
        return await self._run('revise_document',{'document_id':document_id,'instruction':instruction},__user__,__metadata__,__event_emitter__)
