"""Permission-scoped quick task creation from an existing Outline task container."""
import hashlib, os, re, uuid
from urllib.parse import quote
from datetime import date, datetime, timedelta, timezone
from fastapi import HTTPException
from . import outline, permissions, project_service, store, human_tasks, domain, criteria


def enabled():
    return os.getenv('OUTLINE_TASK_CREATION_ENABLED', 'false').lower() == 'true'


def context(user, cid, parent_id, strict=True):
    project = permissions.project(user, cid)
    project_service.ensure_writable(cid)
    mapping = store.get('task-parent:' + cid)
    if not mapping or mapping['id'] != parent_id:
        if strict:raise HTTPException(409, '프로젝트의 업무 목록에서 새 업무를 등록하세요.')
        return None
    parent = outline.api('documents.info', {'id':parent_id}, missing_ok=True)
    if not parent or parent.get('collectionId') != cid or parent.get('parentDocumentId') or not parent.get('publishedAt') or parent.get('archivedAt') or parent.get('deletedAt') or parent.get('template'):
        raise HTTPException(409, '업무 목록의 위치나 상태가 변경되었습니다. 다시 확인하세요.')
    permissions.require_create(user, cid)
    return project


def info(user, cid, parent_id, can_create):
    with outline.MUTEX:
        if not can_create:return {'eligible':False}
        try:project = context(user, cid, parent_id, strict=False)
        except HTTPException as error:
            if error.status_code in (403,404,409):return {'eligible':False}
            raise
        if not project:return {'eligible':False}
        people = permissions.assignees(user, cid)
        if not any(p['email'] == user['email'].lower() for p in people) and not user.get('admin'):
            return {'eligible':False}
        return {'eligible':True, 'project':{'id':cid,'name':project['name']}, 'parentId':parent_id,
                'viewer':{'admin':bool(user.get('admin')),'email':user['email'].lower(),'name':user.get('name') or user['email']},
                'people':[{'id':p['id'],'name':p['name'],'email':p['email']} for p in people],
                'today':datetime.now(timezone(timedelta(hours=9))).date().isoformat()}


def escape(text):
    return re.sub(r'([\\`*_{}\[\]<>#!|])', r'\\\1', text)


def resolve_target(user, cid):
    """Resolve only the registered parent; never create a container during lookup."""
    with outline.MUTEX:
        permissions.project(user, cid)
        project_service.ensure_writable(cid)
        permissions.require_create(user, cid)
        mapping = store.get('task-parent:' + cid)
        if not mapping:
            raise HTTPException(409, '이 컬렉션을 프로젝트로 연결하고 업무 목록을 준비한 뒤 등록하세요.')
        context(user, cid, mapping['id'])
        return {'parentId': mapping['id']}


def fingerprint(body):
    # Server-derived display metadata may change after a response is lost.
    # Preserve the pre-selection fingerprint for ordinary pending requests.
    data = {k:v for k,v in body.items() if k not in ('sourceTitle','sourceUrl') and not (k == 'source' and v is None)}
    return hashlib.sha256(store.dump(data).encode()).hexdigest()


def source_document(user, body, can_read_source):
    source = body.get('source')
    if not source:return None
    if not can_read_source:raise HTTPException(403, '원문 문서를 조회할 권한이 없습니다.')
    document = outline.api('documents.info', {'id':source['documentId']}, missing_ok=True)
    if (not document or document.get('collectionId') != body['collectionId'] or not document.get('publishedAt')
            or document.get('archivedAt') or document.get('deletedAt') or document.get('template')):
        raise HTTPException(422, '원문 문서의 위치나 상태가 변경되었습니다. 문서를 다시 열어 선택하세요.')
    if not source['quote'].strip() or source['to'] <= source['from']:
        raise HTTPException(422, '유효한 텍스트를 선택하세요.')
    return document


def status(user, body, can_create, can_read_source=False):
    """Check a reserved request without creating documents or changing the snapshot."""
    if not can_create:raise HTTPException(403, '업무 목록에 새 문서를 작성할 권한이 없습니다.')
    with outline.MUTEX:
        context(user, body['collectionId'], body['parentDocumentId'])
        source_document(user, body, can_read_source)
        saved = store.get('outline-task-create:' + user['sub'] + ':' + body['requestId'])
        if saved and saved['fingerprint'] != fingerprint(body):
            raise HTTPException(409, '저장 결과를 확인 중인 요청의 내용은 변경할 수 없습니다.')
        return {'reserved':bool(saved)}


def create(user, body, can_create, can_read_source=False):
    if not can_create:raise HTTPException(403, '업무 목록에 새 문서를 작성할 권한이 없습니다.')
    cid, parent_id = body['collectionId'], body['parentDocumentId']
    with outline.MUTEX:
        project = context(user, cid, parent_id)
        source = source_document(user, body, can_read_source)
        people = permissions.assignees(user, cid)
        owner = next((p for p in people if p['id'] == body['ownerId']), None)
        if not owner:raise HTTPException(403, '현재 프로젝트의 활성 구성원만 담당자로 지정할 수 있습니다.')
        if not user.get('admin') and owner['email'] != user['email'].lower():
            raise HTTPException(403, '자신의 업무만 등록할 수 있습니다.')
        title = body['title'].strip()
        if not title:raise HTTPException(422, '업무명을 입력하세요.')
        if any(c in title for c in '\r\n'):raise HTTPException(422, '업무명은 한 줄로 입력하세요.')
        today = datetime.now(timezone(timedelta(hours=9))).date().isoformat()
        start, due = body.get('startDate') or today, body.get('dueDate') or '미정'
        for value in (start,due):
            if value != '미정':
                try:
                    if date.fromisoformat(value).isoformat() != value:raise ValueError()
                except ValueError:raise HTTPException(422, '날짜는 YYYY-MM-DD 형식의 실제 날짜로 입력하세요.')
        if due != '미정' and start > due:raise HTTPException(422, '시작일은 마감일보다 늦을 수 없습니다.')
        result_url = body.get('resultUrl','').strip()
        if result_url and not re.fullmatch(r'https?://[^\s<>]+', result_url):
            raise HTTPException(422, '결과물 링크는 http 또는 https 주소로 입력하세요.')
        items = []
        for item in body['criteria']:
            person = next((p for p in people if p['id'] == item['assigneeId']),None)
            item_title = item['title'].strip()
            if not person:raise HTTPException(403, '완료 기준 담당자는 프로젝트 구성원이어야 합니다.')
            if not item_title or any(c in item_title for c in '\r\n'):raise HTTPException(422, '완료 기준은 한 줄로 입력하세요.')
            items.append(f"- [ ] {escape(item_title)} — 담당자: {human_tasks.label(person['email'])}")
        text = (f"담당자: {human_tasks.label(owner['email'])}\n\n시작일: {start}\n\n마감일: {due}\n\n"
                f"상태: 미착수\n\n진행률: 0%\n\n결과물: {result_url or '없음'}\n\n"
                f"## 업무 내용\n\n{escape(body.get('notes','').strip())}\n\n## 완료 기준\n\n" + '\n'.join(items)).rstrip()
        if source:
            source_url = body.get('sourceUrl','')
            if not re.fullmatch(r'/doc/[^\s<>]+', source_url):
                raise HTTPException(422, '원문 문서 링크를 확인하세요.')
            source_title = ' '.join(body.get('sourceTitle','').split())[:500] or '제목 없음'
            excerpt = '\n'.join('> ' + escape(line) for line in body['source']['quote'].split('\n'))
            text += (f"\n\n## 출처\n\n[{escape(source_title)}]({quote(source_url, safe='/%-')})\n\n"
                     f"원문 확인 버전: {source.get('revision',body['source']['revision'])}\n\n"
                     f"등록 시각: {datetime.now(timezone(timedelta(hours=9))).isoformat(timespec='seconds')}\n\n{excerpt}")
        try:
            domain.parse(text);criteria.parse(text)
        except ValueError as error:raise HTTPException(422, str(error))
        request_fingerprint = fingerprint(body)
        key = 'outline-task-create:' + user['sub'] + ':' + body['requestId']
        saved = store.get(key)
        if saved and saved['fingerprint'] != request_fingerprint:
            raise HTTPException(409, '저장 결과를 확인 중인 요청의 내용은 변경할 수 없습니다.')
        if saved and saved.get('result'):return saved['result']
        if not saved:
            saved = {'id':str(uuid.uuid4()),'fingerprint':request_fingerprint,'text':text}
            store.put(key,saved)
        try:
            document = outline.api('documents.info',{'id':saved['id']},missing_ok=True)
            if not document:
                document = outline.api('documents.create',{'id':saved['id'],'collectionId':cid,'parentDocumentId':parent_id,
                                                           'title':title,'text':saved['text'],'publish':True})
            document = outline.document(saved['id'])
        except Exception as error:
            raise HTTPException(503, '등록 결과를 확인하지 못했습니다. 같은 내용으로 등록 결과 다시 확인을 눌러주세요.') from error
        if document.get('collectionId') != cid or document.get('parentDocumentId') != parent_id or document.get('deletedAt') or document.get('archivedAt'):
            raise HTTPException(409, '생성한 업무 문서의 위치나 상태가 변경되었습니다.')
        task = outline.record(document,user['email'],'created')
        if not task or task.get('error'):raise HTTPException(503, '업무는 생성됐지만 목록 반영을 확인하지 못했습니다. 등록 결과를 다시 확인하세요.')
        result = {'id':document['id'],'title':document['title'],'url':document['url'],'collectionId':cid,'parentDocumentId':parent_id}
        store.put(key,{**saved,'result':result})
        return result
