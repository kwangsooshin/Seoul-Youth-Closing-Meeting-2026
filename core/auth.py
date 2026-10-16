import secrets
import time
from urllib.parse import urlparse
from typing import Optional, Dict
from fastapi import Request, Response, HTTPException
from core.state import state

# 세션 토큰 인메모리 저장소:
# token -> {"created_at": float, "last_activity": float, "absolute_expires_at": float}
_sessions: Dict[str, Dict[str, float]] = {}

IDLE_TIMEOUT_SECONDS = 6 * 3600       # 유휴 만료: 마지막 활동 후 6시간
ABSOLUTE_TIMEOUT_SECONDS = 24 * 3600  # 절대 만료: 최초 로그인 후 24시간
SESSION_TTL_SECONDS = ABSOLUTE_TIMEOUT_SECONDS  # 쿠키 max_age 호환 (최대 24시간)
MAX_ACTIVE_SESSIONS = 100  # 메모리 고갈(DoS) 방지를 위한 최대 동시 세션 수 제한


def cleanup_expired_sessions(now: Optional[float] = None) -> int:
    """만료된 오래된 세션 토큰 일괄 청소 및 정리된 수 반환"""
    if now is None:
        now = time.time()
    cleaned = 0
    for t in list(_sessions.keys()):
        s = _sessions.get(t)
        if not s:
            continue
        if (now > s.get("absolute_expires_at", 0)) or (now - s.get("last_activity", 0) > IDLE_TIMEOUT_SECONDS):
            if _sessions.pop(t, None) is not None:
                cleaned += 1
    return cleaned


def create_admin_token() -> str:
    """안전한 난수 세션 토큰 발급 (유휴 6시간, 절대 24시간 유효)"""
    now = time.time()
    cleanup_expired_sessions(now)

    # 최대 동시 세션 수 초과 시 가장 오래된 세션부터 정리
    while len(_sessions) >= MAX_ACTIVE_SESSIONS:
        oldest_token = min(_sessions.keys(), key=lambda k: _sessions[k].get("last_activity", 0))
        _sessions.pop(oldest_token, None)

    token = f"adm_{secrets.token_urlsafe(32)}"
    _sessions[token] = {
        "created_at": now,
        "last_activity": now,
        "absolute_expires_at": now + ABSOLUTE_TIMEOUT_SECONDS,
    }
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
        _sessions.pop(token, None)
        return False

    # 2. 유휴 만료 체크 (마지막 활동 후 6시간 초과 시 만료)
    if now - session.get("last_activity", 0) > IDLE_TIMEOUT_SECONDS:
        _sessions.pop(token, None)
        return False

    # 3. 정상 활동 확인 -> 마지막 활동 시각 갱신
    session["last_activity"] = now

    # 4. 송출 스크린 세션이 진행 중인 경우 관리자 활동에 맞춰 송출 세션 타이머도 연장(갱신)
    if state.is_started:
        state.touch_session(now)

    return True


def _is_same_origin(request: Request) -> bool:
    """쿠키 기반 상태 변경 요청(POST 등)에 대한 CSRF 방어용 Origin/Referer 검증"""
    target_host = (
        request.headers.get("x-forwarded-host")
        or request.headers.get("host")
        or request.url.netloc
    )
    if not target_host:
        return True
    target_host = target_host.split(",")[0].strip().lower()

    origin = request.headers.get("origin")
    if origin:
        parsed = urlparse(origin)
        return parsed.netloc.lower() == target_host

    referer = request.headers.get("referer")
    if referer:
        parsed = urlparse(referer)
        return parsed.netloc.lower() == target_host

    # 브라우저 외 API 호출이거나 Origin/Referer가 없는 경우 커스텀 헤더 존재 여부 확인
    return bool(request.headers.get("x-requested-with"))


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
        # 쿠키에만 의존하는 상태 변경 요청(POST/PUT/DELETE/PATCH)은 CSRF 방어를 위해 Same-Origin 검증
        if request.method not in ("GET", "HEAD", "OPTIONS") and not _is_same_origin(request):
            return None
        return cookie_token

    return None


def is_authenticated_admin(request: Request) -> bool:
    """
    관리자 세션 토큰 인증 검증:
    1. Authorization: Bearer <token> 헤더 (유효하지 않더라도 쿠키가 유효하면 폴백 허용)
    2. X-Admin-Token: <token> 헤더
    3. admin_token 쿠키 (CSRF 검증 포함)
    """
    token = get_admin_token_from_request(request)
    if token and verify_admin_token(token):
        return True

    # 헤더의 토큰이 만료/불일치하더라도 유효한 HttpOnly 쿠키가 있으면 인정
    cookie_token = request.cookies.get("admin_token", "").strip()
    if cookie_token and cookie_token != token:
        if request.method in ("GET", "HEAD", "OPTIONS") or _is_same_origin(request):
            return verify_admin_token(cookie_token)

    return False


def require_admin(request: Request) -> None:
    """FastAPI Depends용 관리자 인증 의존성 함수"""
    if not is_authenticated_admin(request):
        raise HTTPException(
            status_code=401,
            detail="인증 실패 (유효한 관리자 세션 토큰이 필요합니다)"
        )


def revoke_admin_token(token: Optional[str]):
    """로그아웃 또는 세션 파기 시 토큰 무효화"""
    if token:
        _sessions.pop(token, None)


def is_https_request(request: Request) -> bool:
    """HTTPS 접속 여부 감지 (Render/리버스 프록시 X-Forwarded-Proto 포함)"""
    return (
        request.url.scheme == "https"
        or request.headers.get("x-forwarded-proto", "").split(",")[0].strip().lower() == "https"
    )


def set_admin_cookie(request: Request, response: Response, token: str):
    """보안 속성이 적용된 관리자 인증 쿠키 설정"""
    response.set_cookie(
        key="admin_token",
        value=token,
        max_age=SESSION_TTL_SECONDS,
        httponly=True,
        samesite="lax",
        secure=is_https_request(request),
        path="/",
    )


def clear_admin_cookie(request: Request, response: Response):
    """관리자 인증 쿠키 안전 삭제"""
    response.delete_cookie(
        key="admin_token",
        path="/",
        httponly=True,
        samesite="lax",
        secure=is_https_request(request),
    )


