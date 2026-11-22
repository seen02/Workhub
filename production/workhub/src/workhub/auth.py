"""Authorization for principals authenticated by the signed Outline bridge."""
from fastapi import HTTPException
from .service_identity import ServiceIdentity, for_subject

def allowed(user):
    if not isinstance(user,ServiceIdentity):
        raise HTTPException(401,'Outline 서비스 인증이 필요합니다.')
    return for_subject(user['sub'])

def admin(user):
    if not user.get('admin'):raise HTTPException(403,'관리자 그룹 권한이 필요합니다.')
