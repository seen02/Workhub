"""Version-checked task editing, preview, batch receipts and conservative undo.

Outline documents remain authoritative. Each document is independently committed;
receipts make a retry safe after a partial batch or an uncertain network response.
"""
import hashlib
import re
import uuid
from datetime import date, timedelta

from fastapi import HTTPException
from . import criteria, domain, kanban, outline, permissions, project_service, store, task_status


def context(user, body):
    kanban.context(user, body['collectionId'], body['parentDocumentId'])
    project_service.ensure_writable(body['collectionId'])


def document(user, body, item):
    if not item.get('canUpdate'):
        raise HTTPException(403, '이 업무 문서를 수정할 권한이 없습니다.')
    doc = kanban.child(body['collectionId'], body['parentDocumentId'], item['documentId'])
    permissions.document(user, doc)
    return doc


def version(doc, item):
    if doc.get('revision', 0) != item['revision'] or doc['updatedAt'] != item['updatedAt']:
        raise HTTPException(409, '다른 곳에서 업무가 수정되었습니다. 최신 내용을 확인한 뒤 다시 변경하세요.')


def dated(value):
    if value == '미정':
        return value
    try:
        if date.fromisoformat(value).isoformat() == value:
            return value
    except (ValueError, TypeError):
        pass
    raise ValueError('날짜는 YYYY-MM-DD 형식의 실제 날짜 또는 미정으로 입력하세요.')


def changes(user, doc, change, request_id):
    """Build only editable fields; retain checklist states by their original IDs."""
    fields = domain.parse(doc['text'])
    if not fields:
        raise ValueError('업무 양식을 확인하세요.')
    outline.can_write(user, doc)
    old = criteria.parse(doc['text'])
    effective_status = task_status.summary(doc['text'], old, preserve_human=True, document_id=doc['id'])['status'] if old else fields['status']
    updates = {}
    allowed = {p['email'].lower() for p in permissions.assignees(user, doc['collectionId'])}
    if 'owner' in change:
        owner = change['owner'].strip().lower()
        if owner not in allowed:
            raise HTTPException(403, '프로젝트에 접근 가능한 활성 구성원만 담당자로 지정하세요.')
        updates['owner'] = owner
    for key in ('start', 'due'):
        if key in change:
            updates[key] = dated(change[key])
    if 'shiftDays' in change:
        if any(k in change for k in ('start', 'due')):
            raise ValueError('날짜 지정과 날짜 이동은 함께 사용할 수 없습니다.')
        for key in (('start', 'due') if change.get('shiftBoth') else ('due',)):
            if fields[key] != '미정':
                try:
                    updates[key] = (date.fromisoformat(fields[key]) + timedelta(days=change['shiftDays'])).isoformat()
                except (ValueError, OverflowError):
                    raise ValueError('이동한 날짜가 지원 범위를 벗어납니다.')
    if change.get('transferCriteria') and ('owner' not in change or not user.get('admin')):
        raise HTTPException(403, '완료 기준 담당자 이전은 관리자만 할 수 있습니다.')
    items = None
    if 'criteria' in change:
        if not user.get('admin'):
            raise HTTPException(403, '완료 기준 추가·수정·삭제는 관리자만 할 수 있습니다.')
        previous = {i['id']: i for i in old}
        items = []
        for n, entry in enumerate(change['criteria']):
            code = entry.get('id')
            if code and code not in previous:
                raise ValueError('기존 완료 기준을 확인할 수 없습니다. 최신 업무를 다시 확인하세요.')
            owner = entry['owner'].strip().lower()
            if owner not in allowed and (not code or previous[code]['owner'] != owner):
                raise HTTPException(403, '완료 기준 담당자는 프로젝트의 활성 구성원이어야 합니다.')
            items.append({'id': code or 'C-' + uuid.uuid5(uuid.NAMESPACE_URL, doc['id'] + request_id + str(n)).hex[:8],
                          'title': entry['title'], 'owner': owner,
                          'state': previous[code]['state'] if code else '예정'})
        if old or items:
            items = criteria.validate(items)
    if change.get('transferCriteria'):
        items = items if items is not None else [dict(i) for i in old]
        for item in items:
            if item['owner'] == fields['owner'] and item['state'] != '완료':
                item['owner'] = updates['owner']
    text = doc['text']
    if items is not None and items:
        rollup = criteria.rollup(items)
        if effective_status == '완료' and rollup['status'] != '완료' and not change.get('reopen'):
            raise ValueError('완료한 업무에 미완료 기준을 추가하려면 업무를 다시 열고 저장하세요.')
        text = criteria.replace(text, items)
        # Adding/removing checklist work changes the aggregate status too. Pure
        # renames, reordering and reassignment keep an explicitly selected status.
        workload_changed = sorted(i['state'] for i in old) != sorted(i['state'] for i in items)
        summary = rollup if workload_changed else task_status.summary(text, items, preserve_human=True, document_id=doc['id'])
        # Human templates omit progress writes when criteria are present. Write the
        # header before replacing the checklist, then let projection derive it.
        updates.update(summary)
    if updates:
        text = domain.patch_text(text, updates)
    # Parse the result again so date inversions and invalid checklist edits never write.
    after_fields = domain.parse(text)
    after_items = criteria.parse(text)
    if after_items:
        after_fields.update(task_status.summary(text, after_items, preserve_human=True, document_id=doc['id']))
    before_fields = dict(fields)
    if old:
        before_fields.update(task_status.summary(doc['text'], old, preserve_human=True, document_id=doc['id']))
    return text, {'before': before_fields, 'after': after_fields, 'beforeCriteria': old, 'afterCriteria': after_items}


def history(text, user, label, detail):
    fence = '`' * max(3, 1 + max((len(m.group()) for m in re.finditer(r'`+', detail)), default=0))
    return text.rstrip() + f"\n\n### 보고 기록\n\n{store.now()} · {user['email']}\n\n{fence}text\n{label}\n{detail}\n{fence}"


def describe(info):
    lines = [f"{domain.FIELDS[k]}: {info['before'].get(k)} → {info['after'].get(k)}"
             for k in ('owner', 'start', 'due', 'status', 'progress') if info['before'].get(k) != info['after'].get(k)]
    if info['beforeCriteria'] != info['afterCriteria']:
        lines += ['이전 완료 기준: ' + store.dump(info['beforeCriteria']),
                  '변경 완료 기준: ' + store.dump(info['afterCriteria'])]
    return '\n'.join(lines)


def preview(user, body):
    with outline.MUTEX:
        context(user, body)
        results = []
        for item in body['edits']:
            try:
                doc = document(user, body, item)
                version(doc, item)
                _, info = changes(user, doc, item['changes'], body['requestId'])
                results.append({'id': doc['id'], 'title': doc['title'], 'ok': True, **info})
            except (HTTPException, ValueError) as error:
                results.append(failure(item, error))
        return {'results': results}


def failure(item, error):
    return {'id': item['documentId'], 'ok': False,
            'code': error.status_code if isinstance(error, HTTPException) else 422,
            'error': str(error.detail) if isinstance(error, HTTPException) else str(error)}


def key(user, body):
    return 'task-edit:' + user['sub'] + ':' + body['requestId']


def write(user, body, item, receipt_key, undo=False):
    """Persist intent before the external write and verify a lost response by reading."""
    doc = document(user, body, item)
    saved = store.get(receipt_key)
    fingerprint = hashlib.sha256(store.dump(item).encode()).hexdigest()
    if saved and saved['fingerprint'] != fingerprint:
        raise HTTPException(409, '같은 요청 번호로 변경 내용을 바꿀 수 없습니다.')
    if saved and saved.get('done'):
        return {'id': doc['id'], 'ok': True, 'card': kanban.card(user, doc, True, permissions.assignees(user, doc['collectionId']))}
    if not saved:
        if undo:
            original = store.get(key(user, body) + ':' + doc['id'])
            if not original or not original.get('done'):
                raise HTTPException(409, '완료된 본인의 변경만 취소할 수 있습니다.')
            # Never undo intervening native edits, checklist reports, or reassignment.
            if doc['text'] != original['verifiedText'] or doc.get('revision', 0) != original['verifiedRevision'] or doc['updatedAt'] != original['verifiedAt']:
                raise HTTPException(409, '이후에 다른 수정이 있어 실행 취소할 수 없습니다. 최신 업무를 확인하세요.')
            outline.can_write(user, {**doc, 'text': original['before']})
            before_fields = domain.parse(original['before'])
            before_items = criteria.parse(original['before'])
            allowed = {p['email'] for p in permissions.assignees(user, doc['collectionId'])}
            if before_fields['owner'] not in allowed or any(i['owner'] not in allowed for i in before_items):
                raise HTTPException(409, '이전 담당자가 현재 프로젝트의 활성 구성원이 아니어서 실행 취소할 수 없습니다.')
            suffix = doc['text'][len(domain.source_text(doc['text'])):]
            after = history(domain.source_text(original['before']) + suffix, user, '빠른 수정 실행 취소', doc['title'])
        else:
            version(doc, item)
            after, info = changes(user, doc, item['changes'], body['requestId'])
            detail = describe(info)
            if not detail:
                return {'id': doc['id'], 'ok': True, 'unchanged': True,
                        'card': kanban.card(user, doc, True, permissions.assignees(user, doc['collectionId']))}
            after = history(after, user, '업무 빠른 수정', detail)
        saved = {'fingerprint': fingerprint, 'before': doc['text'], 'after': after,
                 'revision': doc.get('revision', 0), 'updatedAt': doc['updatedAt'], 'attempted': False}
        store.put(receipt_key, saved)
    else:
        # A retry may follow an assignment away from the current user. Check the
        # original owner and current signed document grant instead of denying recovery.
        authority = store.get(key(user, body) + ':' + doc['id'])['before'] if undo else saved['before']
        outline.can_write(user, {**doc, 'text': authority})
        if undo:
            allowed = {p['email'] for p in permissions.assignees(user, doc['collectionId'])}
            if domain.parse(authority)['owner'] not in allowed or any(i['owner'] not in allowed for i in criteria.parse(authority)):
                raise HTTPException(409, '이전 담당자의 프로젝트 접근 권한을 다시 확인하세요.')
        if not undo:
            # A role or assignment can be revoked while a request is pending.
            # Re-authorize structural operations before any possible retry write.
            changes(user, {**doc, 'text': saved['before']}, item['changes'], body['requestId'])
    if saved['attempted'] and domain.same_saved_text(saved['after'], doc['text']):
        pass
    elif doc['text'] != saved['before'] or doc.get('revision', 0) != saved['revision'] or doc['updatedAt'] != saved['updatedAt']:
        raise HTTPException(409, '원본이 변경되어 저장을 중단했습니다. 최신 내용을 확인하세요.')
    else:
        store.put(receipt_key, {**saved, 'attempted': True})
        try:
            outline.api('documents.update', {'id': doc['id'], 'text': saved['after'], 'lastRevision': saved['revision']})
            doc = kanban.child(body['collectionId'], body['parentDocumentId'], doc['id'])
        except Exception as error:
            try:
                doc = kanban.child(body['collectionId'], body['parentDocumentId'], doc['id'])
            except Exception:
                raise HTTPException(503, '저장 결과를 확인 중입니다. 같은 요청으로 다시 확인하세요.') from error
            if not domain.same_saved_text(saved['after'], doc['text']):
                raise HTTPException(503, '저장 결과를 확인 중입니다. 같은 요청으로 다시 확인하세요.') from error
        if not domain.same_saved_text(saved['after'], doc['text']):
            raise HTTPException(409, '원본이 변경되어 결과를 확정하지 못했습니다.')
    task_status.remember(doc['id'], doc['text'])
    outline.record(doc, user['email'], 'task-edit-undo' if undo else 'task-edit')
    store.put(receipt_key, {**saved, 'done': True, 'verifiedText': doc['text'],
                            'verifiedRevision': doc.get('revision', 0), 'verifiedAt': doc['updatedAt']})
    return {'id': doc['id'], 'ok': True, 'card': kanban.card(user, doc, True, permissions.assignees(user, doc['collectionId']))}


def mutate(user, body, undo=False):
    with outline.MUTEX:
        context(user, body)
        receipt = key(user, body)
        # Bind the complete batch to its request, before any item can commit.
        identity = {k: body[k] for k in ('collectionId', 'parentDocumentId', 'edits')}
        identity['edits'] = [{k: v for k, v in i.items() if k != 'canUpdate'} for i in body['edits']]
        fingerprint = hashlib.sha256(store.dump(identity).encode()).hexdigest()
        batch = store.get(receipt)
        if not undo and batch and batch['fingerprint'] != fingerprint:
            raise HTTPException(409, '같은 요청 번호로 변경 대상이나 내용을 바꿀 수 없습니다.')
        if undo and not batch:
            raise HTTPException(409, '본인의 저장 요청을 확인할 수 없습니다.')
        if undo and (batch.get('collectionId') != body['collectionId'] or batch.get('parentDocumentId') != body['parentDocumentId']):
            raise HTTPException(409, '원래 변경한 프로젝트의 업무 목록에서 실행 취소하세요.')
        if not undo:
            store.put(receipt, {'fingerprint': fingerprint, 'collectionId': body['collectionId'],
                                'parentDocumentId': body['parentDocumentId']})
        results = []
        for item in body['edits']:
            try:
                results.append(write(user, body, item, receipt + ':' + item['documentId'] + (':undo' if undo else ''), undo))
            except (HTTPException, ValueError) as error:
                results.append(failure(item, error))
            except Exception:
                results.append(failure(item, HTTPException(503, '저장 결과를 확인 중입니다. 같은 요청으로 다시 확인하세요.')))
        return {'requestId': body['requestId'], 'results': results}
