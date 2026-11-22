"""One permission-scoped statistics service for Workhub and Outline."""
import os
from fastapi import HTTPException
from . import analytics, auth, directory, outline, permissions, store


def enabled():
    return os.getenv('OUTLINE_ANALYTICS_ENABLED', 'false').lower() == 'true'


def capabilities(user, include_projects=False):
    result = {'enabled': True, 'admin': bool(user.get('admin')),
            'email': user['email'].lower(), 'name': user.get('name') or user['email'],
            'default_scope': 'managed' if user.get('admin') else 'all',
            'workhub_url': outline.PUBLIC + '/workhub/projects'}
    if include_projects:
        result['linked_ids'] = [p['id'] for p in permissions.projects(user)]
    return result


def query(user, collection_id='', owner='', horizon=7, managed=False, strict=False):
    """Read one snapshot; never give a role access to an Outline collection."""
    owner = owner.strip().lower()
    if not user.get('admin'):
        if owner and owner != user['email'].lower():
            raise HTTPException(403, '다른 사용자의 진행 통계는 관리자만 조회할 수 있습니다.')
        owner = user['email'].lower()
    with outline.MUTEX:
        if collection_id:
            permissions.project(user, collection_id)
        projects = permissions.projects(user)
        linked_ids = [p['id'] for p in projects]
        if managed:
            auth.admin(user)
            projects = [p for p in projects if p.get('manager', '').lower() == user['email'].lower()]
        if strict and collection_id and collection_id not in {p['id'] for p in projects}:
            raise HTTPException(422, '현재 프로젝트 범위에 포함되지 않습니다. 접근 가능한 전체 프로젝트를 선택하세요.')
        allowed = {p['id'] for p in projects}
        visible = [t for t in outline.tasks(collection_id, user) if t.get('collectionId') in allowed]
        if not user.get('admin'):
            visible = [t for t in visible if t.get('fields', {}).get('owner', '').lower() == owner
                       or any(i['owner'].lower() == owner for i in t.get('criteria', []))]
        members = None
        if user.get('admin'):
            members = {p['email']: p for project in projects if not collection_id or project['id'] == collection_id
                       for p in permissions.assignees(user, project['id'])}
        emails = {t.get('fields', {}).get('owner', '').lower() for t in visible}
        emails.update(i['owner'].lower() for t in visible for i in t.get('criteria', []))
        if members is not None:
            emails.update(members)
        emails.discard('')
        if strict and owner and owner not in emails and owner != user['email'].lower():
            raise HTTPException(422, '선택한 담당자가 현재 프로젝트 범위에 없습니다. 담당자 선택을 해제하세요.')
        data = analytics.build(visible, projects, owner, collection_id, horizon, owner_members=members)
        if user.get('admin'):
            overview = analytics.build(visible, projects, collection_id=collection_id, horizon=horizon, owner_members=members)
            data['portfolio'] = {'summary': overview['summary'], 'projects': overview['projects']}
        else:
            # Shared tasks retain task-level progress, but only the viewer's criteria.
            for row in data['actions'] + data['completed_tasks']:
                row['criteria'] = [i for i in row['criteria'] if i['owner'].lower() == owner]
            data['calendar_actions'] = data['actions']
        labels = directory.names()
        if members is not None:
            labels.update({email: p['name'] for email, p in members.items()})
        # Only labels of people in this permitted project range are returned.
        relevant = emails | {user['email'].lower()} | {p.get('manager', '').lower() for p in projects}
        if not user.get('admin'):
            relevant = {owner} | {t['owner'].lower() for t in data['actions'] + data['completed_tasks']} | {p.get('manager', '').lower() for p in projects}
        data.update(owners_scope='project_members' if members is not None else 'selected_owner', managed=managed,
                    owner_options=[{'email': e, 'name': labels.get(e, e)} for e in sorted(emails if user.get('admin') else {owner})],
                    filter_options={'projects': [{'id': p['id'], 'name': p['name']} for p in projects]},
                    viewer=capabilities(user), names={e: labels.get(e, e) for e in relevant if e},
                    generated_at=store.now(), linked_ids=linked_ids,
                    sync={k: v for k, v in (store.get('last_sync') or {}).items() if k in ('at', 'ok')})
        return data
