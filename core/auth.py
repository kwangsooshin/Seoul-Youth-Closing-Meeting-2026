import secrets
import time
from typing import Optional, Dict
from fastapi import Request

# 세션 토큰 인메모리 저장소:
# token -> {"created_at": float, "last_activity": float, "absolute_expires_at": float}
_sessions: Dict[str, Dict[str, float]] = {}

IDLE_TIMEOUT_SECONDS = 6 * 3600       # 유휴 만료: 마지막 활동 후 6시간
ABSOLUTE_TIMEOUT_SECONDS = 24 * 3600  # 절대 만료: 최초 로그인 후 24시간
SESSION_TTL_SECONDS = ABSOLUTE_TIMEOUT_SECONDS  # 쿠키 max_age 호환 (최대 24시간)


def _cleanup_expired_sessions(now: float):
    """만료된 오래된 세션 토큰 일괄 청소"""
    for t in list(_sessions.keys()):
        s = _sessions.get(t)
        if not s:
            continue
        if (now > s.get("absolute_expires_at", 0)) or (now - s.get("last_activity", 0) > IDLE_TIMEOUT_SECONDS):
            del _sessions[t]


def create_admin_token() -> str:
    """안전한 난수 세션 토큰 발급 (유휴 6시간, 절대 24시간 유효)"""
    token = f"adm_{secrets.token_urlsafe(32)}"
    now = time.time()
    _sessions[token] = {
        "created_at": now,
        "last_activity": now,
        "absolute_expires_at": now + ABSOLUTE_TIMEOUT_SECONDS,
    }

    # 만료된 오래된 세션 토큰 청소
    _cleanup_expired_sessions(now)

    return token


def verify_admin_token(token: Optional[str]) -> bool:
    """세션 토큰 유효성 검증 및 유휴 시간 갱신 (슬라이딩 세션)"""
    if not token:
        return False
    session = _sessions.get(token)
    if not session:
        return False

    now = time.time()
    # 1. 절대 만료 체크 (최초 로그인 후 24시간 초과 시 무조건 만료)
    if now > session.get("absolute_expires_at", 0):
        del _sessions[token]
        return False

    # 2. 유휴 만료 체크 (마지막 활동 후 6시간 초과 시 만료)
    if now - session.get("last_activity", 0) > IDLE_TIMEOUT_SECONDS:
        del _sessions[token]
        return False

    # 3. 정상 활동 확인 -> 마지막 활동 시각 갱신
    session["last_activity"] = now

    # 4. 송출 스크린 세션이 진행 중인 경우 관리자 활동에 맞춰 송출 세션 타이머도 연장(갱신)
    try:
        from core.state import state
        if state.is_started:
            state.touch_session(now)
    except Exception:
        pass

    return True


def get_admin_token_from_request(request: Request) -> Optional[str]:
    """요청에서 관리자 토큰(Authorization 헤더, X-Admin-Token 헤더, admin_token 쿠키) 추출"""
    auth_header = request.headers.get("authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()
        if token:
            return token

    custom_token = request.headers.get("x-admin-token", "").strip()
    if custom_token:
        return custom_token

    cookie_token = request.cookies.get("admin_token", "").strip()
    if cookie_token:
        return cookie_token

    return None


def is_authenticated_admin(request: Request) -> bool:
    """
    관리자 세션 토큰 인증 검증:
    1. Authorization: Bearer <token> 헤더
    2. X-Admin-Token: <token> 헤더
    3. admin_token 쿠키
    """
    token = get_admin_token_from_request(request)
    return verify_admin_token(token)


def revoke_admin_token(token: Optional[str]):
    """로그아웃 또는 세션 파기 시 토큰 무효화"""
    if token and token in _sessions:
        del _sessions[token]

