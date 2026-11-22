"""Live project board. Document grants are supplied only by the signed Outline server."""
import hashlib, os, re
from datetime import datetime, timedelta, timezone
from fastapi import HTTPException
from . import outline, permissions, project_service, store, domain, criteria, task_status


def enabled():
    return os.getenv('OUTLINE_KANBAN_ENABLED', 'false').lower() == 'true'


def context(user, cid, parent_id, strict=True):
    project = permissions.project(user, cid)
    pointer = store.get('task-parent:' + cid)
    if not pointer or pointer.get('id') != parent_id:
        if strict:raise HTTPException(409, '현재 프로젝트의 업무 목록에서 확인하세요.')
        return None
    parent = outline.api('documents.info', {'id':parent_id}, missing_ok=True)
    if not parent or parent.get('collectionId') != cid or parent.get('parentDocumentId') or not active(parent):
        raise HTTPException(409, '업무 목록의 위치나 상태가 변경되었습니다.')
    return project


def active(doc):
    return bool(doc.get('publishedAt')) and not any(doc.get(k) for k in ('archivedAt','deletedAt','template'))


def info(user, cid, parent_id):
    with outline.MUTEX:
        try:project = context(user, cid, parent_id, strict=False)
        except HTTPException as error:
            if error.status_code in (403,404,409):return {'eligible':False}
            raise
        return {'eligible':bool(project)}


def child(cid, parent_id, doc_id):
    doc = outline.api('documents.info', {'id':doc_id}, missing_ok=True)
    if not doc or doc.get('collectionId') != cid or doc.get('parentDocumentId') != parent_id or not active(doc):
        raise HTTPException(409, '업무 문서의 위치나 상태가 변경되었습니다. 새로고침하세요.')
    return doc


def card(user, doc, can_update, people):
    task = outline.projected(doc)
    reason = task.get('error') if task else '업무 양식이 없는 문서입니다.'
    basic = {'id':doc['id'],'title':doc['title'],'url':doc['url']}
    if reason:return {**basic,'unclassified':True,'reason':reason}
    fields, items = task['fields'], task['criteria']
    email = user['email'].lower()
    writable = can_update
    try:permissions.document(user, doc)
    except HTTPException:writable = False
    owner = fields['owner'].lower()
    names = {p['email'].lower():p['name'] for p in people}
    return {**basic,'unclassified':False,'owner':owner,'ownerName':names.get(owner, owner),
            'status':fields['status'],'progress':None if fields['progress']=='미기재' else float(fields['progress'].rstrip('%')),
            'start':fields.get('start','미정'),'due':fields['due'],
            'revision':doc.get('revision',0),'updatedAt':doc['updatedAt'],
            'canMove':bool(writable and (user.get('admin') or owner == email)),
            'criteria':[dict(i, ownerName=names.get(i['owner'],i['owner']),
                             canUpdate=bool(writable and (user.get('admin') or i['owner'] == email))) for i in items]}


def query(user, cid, parent_id, grants):
    with outline.MUTEX:
        project = context(user, cid, parent_id)
        people = permissions.assignees(user, cid)
        cards = [card(user, child(cid,parent_id,g['id']),g['canUpdate'],people) for g in grants]
        return {'projectName':project['name'],'viewer':{'email':user['email'].lower(),'admin':bool(user.get('admin'))},
                'people':[{'email':p['email'],'name':p['name']} for p in people],
                'cards':cards,'refreshedAt':store.now(),
                'today':datetime.now(timezone(timedelta(hours=9))).date().isoformat()}


def mutate(user, body, can_update):
    if not can_update:raise HTTPException(403, '이 업무 문서를 수정할 권한이 없습니다.')
    cid, parent_id, did = body['collectionId'], body['parentDocumentId'], body['documentId']
    with outline.MUTEX:
        context(user,cid,parent_id)
        project_service.ensure_writable(cid)
        doc = child(cid,parent_id,did)
        if body.get('criterionId'):
            if body.get('status') or body.get('criterionState') not in criteria.STATES:
                raise HTTPException(422, '완료 기준 상태를 확인하세요.')
            changes = {'criterion_states':{body['criterionId']:body['criterionState']}}
        else:
            if body.get('criterionState') or body.get('status') not in domain.STATES:
                raise HTTPException(422, '업무 상태를 확인하세요.')
            changes = {'kanban_status':body['status']}
            fields = domain.parse(doc['text'])
            if not fields:raise HTTPException(422, '업무 양식을 확인하세요.')
            items = criteria.parse(doc['text'])
            if items:fields['status'] = task_status.summary(doc['text'],items,preserve_human=True,document_id=did)['status']
        outline.authorize_changes(user,doc,changes)
        fingerprint = hashlib.sha256(store.dump(body).encode()).hexdigest()
        key = 'outline-kanban:' + user['sub'] + ':' + body['requestId']
        saved = store.get(key)
        if saved and saved['fingerprint'] != fingerprint:
            raise HTTPException(409, '결과 확인 중인 요청의 내용은 변경할 수 없습니다.')
        if saved and saved.get('result'):return saved['result']
        if not saved:
            if doc.get('revision',0) != body['revision'] or doc['updatedAt'] != body['updatedAt']:
                raise HTTPException(409, '다른 곳에서 업무가 수정되었습니다. 새로고침 후 다시 변경하세요.')
            after = outline.apply_changes(doc['text'],changes,did)
            if 'criterion_states' in changes:
                # An explicit checklist edit in Outline resumes status rollup,
                # even when a prior card move selected a manual status.
                after = domain.patch_text(after, criteria.rollup(criteria.parse(after)))
            if 'kanban_status' in changes:
                before_items = criteria.parse(doc['text'])
                completed = [i for i in before_items if i['state'] != '완료'] if body['status'] == '완료' else []
                reset = [i for i in before_items if i['state'] != '예정'] if fields['status']=='완료' and body['status']=='미착수' else []
                label = '칸반에서 일괄 완료' if completed else ('칸반에서 완료 기준 초기화' if reset else '칸반 상태 변경')
                history = f"{label}\n이전 상태: {fields['status']} → {body['status']}"
                if completed:history += '\n완료 처리한 기준: ' + ', '.join(f"{i['title']} ({i['state']} → 완료)" for i in completed)
                if reset:history += '\n체크 해제한 기준: ' + ', '.join(f"{i['title']} ({i['state']} → 예정)" for i in reset)
                fence = '`' * max(3,1+max((len(m.group()) for m in re.finditer(r'`+',history)),default=0))
                after += f"\n\n### 보고 기록\n\n{store.now()} · {user['email']}\n\n{fence}text\n{history}\n{fence}"
            saved = {'fingerprint':fingerprint,'before':doc['text'],'after':after,
                     'revision':doc.get('revision',0),'updatedAt':doc['updatedAt'],'attempted':False}
            store.put(key,saved)
        if saved['attempted'] and domain.same_saved_text(saved['after'],doc['text']):
            pass
        elif doc['text'] != saved['before'] or doc.get('revision',0) != saved['revision'] or doc['updatedAt'] != saved['updatedAt']:
            raise HTTPException(409, '원본이 변경되어 자동 저장을 중단했습니다. 원본을 확인하고 새로고침하세요.')
        else:
            saved['attempted'] = True
            store.put(key,saved)
            try:
                outline.api('documents.update',{'id':did,'text':saved['after'],'lastRevision':saved['revision']})
                doc = child(cid,parent_id,did)
            except Exception as error:
                try:doc = child(cid,parent_id,did)
                except Exception:raise HTTPException(503, '저장 결과를 확인하지 못했습니다. 반영 결과 다시 확인을 누르세요.') from error
                if not domain.same_saved_text(saved['after'],doc['text']):
                    raise HTTPException(503, '저장 결과를 확인하지 못했습니다. 반영 결과 다시 확인을 누르세요.') from error
            if not domain.same_saved_text(saved['after'],doc['text']):
                raise HTTPException(409, '원본이 변경되어 반영 결과를 확정하지 못했습니다. 원본을 확인하세요.')
        task_status.remember(did,doc['text'],kanban='kanban_status' in changes)
        outline.record(doc,user['email'],'kanban')
        result = card(user,doc,can_update,permissions.assignees(user,cid))
        store.put(key,{**saved,'result':result})
        return result
