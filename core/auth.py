import secrets
import time
from typing import Optional, Dict
from fastapi import Request
from core.config import ADMIN_PASSWORD

# 세션 토큰 인메모리 저장소: token -> expire_timestamp
_sessions: Dict[str, float] = {}
SESSION_TTL_SECONDS = 24 * 3600  # 24시간 동안 유효


def create_admin_token() -> str:
    """안전한 난수 세션 토큰 발급 (24시간 유효)"""
    token = f"adm_{secrets.token_urlsafe(32)}"
    now = time.time()
    _sessions[token] = now + SESSION_TTL_SECONDS

    # 만료된 오래된 세션 토큰 청소
    for t in list(_sessions.keys()):
        if _sessions[t] < now:
            del _sessions[t]

    return token


def verify_admin_token(token: Optional[str]) -> bool:
    """세션 토큰 유효성 검증"""
    if not token:
        return False
    now = time.time()
    expire_time = _sessions.get(token)
    if expire_time and expire_time > now:
        return True
    return False


def is_authenticated_admin(request: Request, legacy_password: Optional[str] = None) -> bool:
    """
    관리자 인증 검증:
    1. Authorization: Bearer <token> 헤더
    2. X-Admin-Token: <token> 헤더
    3. 하위 호환용 레거시 비밀번호 검증
    """
    # 1. Bearer Token
    auth_header = request.headers.get("authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()
        if verify_admin_token(token):
            return True

    # 2. X-Admin-Token
    custom_token = request.headers.get("x-admin-token", "").strip()
    if verify_admin_token(custom_token):
        return True

    # 3. 하위 호환 (레거시 비밀번호 파라미터)
    if legacy_password and legacy_password == ADMIN_PASSWORD:
        return True

    return False


def revoke_admin_token(token: Optional[str]):
    """로그아웃 또는 세션 파기 시 토큰 무효화"""
    if token and token in _sessions:
        del _sessions[token]

