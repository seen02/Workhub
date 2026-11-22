
    async def read_outline_attachment(self, filename: str = '', __files__: list = None, __user__: dict = None, __metadata__: dict = None, __event_emitter__=None) -> str:
        """현재 채팅에 첨부된 TXT/MD/CSV/DOCX/텍스트 PDF를 읽습니다. 파일 하나면 filename 생략 가능, 여러 개면 정확한 이름 지정. 반환 file_id로 prepare_outline_draft 호출. 이미지 OCR 미지원."""
        from open_webui.models.files import Files
        from open_webui.storage.provider import Storage
        records=[]
        for item in (__files__ or []):
            fid=item.get('id') or item.get('file',{}).get('id')
            if not fid: continue
            f=await Files.get_file_by_id(fid)
            if f and f.user_id==(__user__ or {}).get('id'):
                records.append(f)
        records=list({f.id:f for f in records}.values())
        matches=records if len(records)==1 else [f for f in records if filename and (filename.casefold() in f.filename.casefold() or filename.casefold() in (f.meta or {}).get('name','').casefold())]
        if len(matches)!=1:
            return json.dumps({'status':'needs_input','error':{'needs_input':True,'message':'읽을 파일을 먼저 첨부해 주세요.' if not records else '어느 첨부파일을 읽을까요?','candidates':[{'name':f.filename} for f in records]}},ensure_ascii=False)
        f=matches[0]
        def read_bytes():
            path=Path(Storage.get_file(f.path))
            if path.stat().st_size>8*1024*1024: raise ValueError('8MB 초과')
            return path.read_bytes()
        try: raw=await asyncio.to_thread(read_bytes)
        except Exception as exc: return json.dumps({'status':'failed','error':'첨부 읽기 실패: '+str(exc)},ensure_ascii=False)
        return await self._run('ingest_attachment', {'name':f.filename,'file_id':f.id,'base64':base64.b64encode(raw).decode()}, __user__, __metadata__, __event_emitter__)
