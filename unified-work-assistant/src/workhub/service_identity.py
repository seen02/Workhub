"""Resolve principals already authenticated by a trusted service, without portal tokens.

This is not a public login endpoint. Callers must authenticate the source (Rocket.Chat
server messages, signed Outline requests, or the authenticated WebUI bridge) first.
Directory membership proves authorization, not that a browser has logged in.
"""
from fastapi import HTTPException
from . import lifecycle, store


class ServiceIdentity(dict):
    """In-process provenance; JSON claims cannot opt into service authentication."""


def for_subject(subject):
    if not lifecycle.enabled():
        raise HTTPException(503, 'Authentik 계정 동기화 설정이 필요합니다. 관리자에게 문의하세요.')
    if not isinstance(subject, str) or not subject:
        raise HTTPException(401, 'Authentik 사용자 연결을 확인할 수 없습니다.')
    row = store.get('employee:' + subject)
    if not row or row.get('sub') != subject:
        raise HTTPException(403, '업무 계정 동기화가 필요합니다. 잠시 후 다시 시도하거나 관리자에게 계정 연결을 확인해 주세요.')
    if row.get('review') or row.get('removed') or not row.get('email'):
        raise HTTPException(403, '계정 연결에 관리자 확인이 필요합니다.')
    try:
        person = lifecycle.auth_api('core/users/' + str(row['pk']) + '/')
        groups = [group['name'] for group in person.get('groups_obj', [])]
    except Exception:
        raise HTTPException(503, '현재 Authentik 계정 권한을 확인하지 못했습니다.')
    if str(person.get('uuid')) != subject or not lifecycle.eligible(person):
        raise HTTPException(403, '업무 서비스 이용이 중지되었거나 계정 연결이 일치하지 않습니다.')
    if (person.get('email', '').lower() != row['email'] or
            person.get('username') != row.get('username')):
        raise HTTPException(403, '이메일·로그인 ID 변경은 관리자 계정 연결 확인이 필요합니다.')
    # Include historical accounts: recycling an email must never merge identities.
    if any(other.get('email') == row['email'] and other.get('sub') != subject
           for other in lifecycle.records()):
        raise HTTPException(403, '이메일이 중복된 계정입니다. 관리자 확인이 필요합니다.')
    user = ServiceIdentity(sub=subject, email=row['email'],
                           name=person.get('name') or person['username'],
                           groups=groups, admin=lifecycle.ADMIN in groups)
    lifecycle.require_identity(user)
    # Do not invent an email_verified OIDC claim. This identity is authenticated
    # through the source service and the administrator-managed immutable mapping.
    return user
