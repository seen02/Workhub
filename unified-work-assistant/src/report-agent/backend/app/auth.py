from dataclasses import dataclass
from functools import lru_cache

from fastapi import Header, HTTPException

from .config import get_settings


@dataclass(frozen=True)
class DemoIdentity:
    role: str
    employee_id: int | None = None

    @property
    def is_manager(self) -> bool:
        return self.role == "manager"


def get_identity(
    x_demo_role: str = Header(default="manager"),
    x_demo_employee_id: int | None = Header(default=None),
    authorization: str | None = Header(default=None),
) -> DemoIdentity:
    settings = get_settings()
    if settings.auth_mode.lower() == "jwt":
        return _get_jwt_identity(authorization)
    if settings.auth_mode.lower() != "demo":
        raise HTTPException(status_code=503, detail="지원하지 않는 AUTH_MODE 설정입니다.")
    role = x_demo_role.lower().strip()
    if role not in {"manager", "employee"}:
        raise HTTPException(status_code=400, detail="지원하지 않는 데모 역할입니다.")
    if role == "employee" and not x_demo_employee_id:
        raise HTTPException(status_code=401, detail="직원 데모 ID가 필요합니다.")
    return DemoIdentity(role=role, employee_id=x_demo_employee_id)


@lru_cache
def _jwks_client(url: str):
    import jwt

    return jwt.PyJWKClient(url, cache_keys=True)


def _get_jwt_identity(authorization: str | None) -> DemoIdentity:
    import jwt

    settings = get_settings()
    if not settings.jwt_jwks_url or not settings.jwt_issuer or not settings.jwt_audience:
        raise HTTPException(status_code=503, detail="JWT SSO 환경설정이 완료되지 않았습니다.")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="SSO Bearer 토큰이 필요합니다.")
    token = authorization.removeprefix("Bearer ").strip()
    try:
        key = _jwks_client(settings.jwt_jwks_url).get_signing_key_from_jwt(token).key
        claims = jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            audience=settings.jwt_audience,
            issuer=settings.jwt_issuer,
            options={"require": ["exp", "iat", "sub"]},
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail="유효하지 않은 SSO 토큰입니다.") from exc
    raw_roles = claims.get(settings.jwt_role_claim, "")
    roles = raw_roles if isinstance(raw_roles, list) else [raw_roles]
    if settings.jwt_manager_role in roles:
        return DemoIdentity(role="manager")
    employee_value = claims.get(settings.jwt_employee_id_claim)
    try:
        employee_id = int(employee_value)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=403, detail="SSO 토큰에 직원 ID가 없습니다.") from exc
    return DemoIdentity(role="employee", employee_id=employee_id)


def require_manager(identity: DemoIdentity) -> None:
    if not identity.is_manager:
        raise HTTPException(status_code=403, detail="관리자만 조회할 수 있는 정보입니다.")


def require_owner_or_manager(identity: DemoIdentity, employee_id: int) -> None:
    if not identity.is_manager and identity.employee_id != employee_id:
        raise HTTPException(status_code=403, detail="본인의 업무보고만 처리할 수 있습니다.")
