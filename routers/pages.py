import time
from typing import Dict, Tuple
from fastapi import APIRouter, Request, BackgroundTasks, HTTPException
from fastapi.responses import HTMLResponse, FileResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from core.config import BASE_DIR
from core.auth import verify_admin_token, revoke_admin_token, clear_admin_cookie
from core.net import get_client_ip
from db import save_access_log

router = APIRouter(tags=["Pages"])

templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

# 감사 로그(Audit Log) 도배/DB 부하 방지를 위한 단기 쿨다운 캐시: (ip, page_type) -> last_logged_ts
_audit_cooldown_cache: Dict[Tuple[str, str], float] = {}
AUDIT_COOLDOWN_SECONDS = 3.0


def record_audit(request: Request, page_type: str):
    """페이지 접속 감사 로그(Audit Log)를 백그라운드로 안전하게 DB 저장 (단기 중복 도배 방지 포함)"""
    try:
        now = time.time()
        ip = get_client_ip(request)[:45]
        key = (ip, page_type)

        if len(_audit_cooldown_cache) > 500:
            stale = [k for k, ts in _audit_cooldown_cache.items() if now - ts > 60.0]
            for k in stale:
                _audit_cooldown_cache.pop(k, None)

        last_ts = _audit_cooldown_cache.get(key, 0.0)
        if now - last_ts < AUDIT_COOLDOWN_SECONDS:
            return
        _audit_cooldown_cache[key] = now

        path = request.url.path[:255]
        user_agent = request.headers.get("user-agent", "")[:255]
        save_access_log(ip=ip, page_type=page_type, path=path, user_agent=user_agent)
    except Exception as e:
        print(f"[WARN] 감사 로그 기록 실패: {e}")


@router.get("/", response_class=HTMLResponse)
async def display_page(request: Request, background_tasks: BackgroundTasks):
    """현장 송출용 화면 (대형 스크린 / 관객용)"""
    background_tasks.add_task(record_audit, request, "display")
    return templates.TemplateResponse(request=request, name="display.html")


@router.get("/display", response_class=HTMLResponse)
async def display_alias(request: Request, background_tasks: BackgroundTasks):
    background_tasks.add_task(record_audit, request, "display")
    return templates.TemplateResponse(request=request, name="display.html")


@router.get("/admin/login", response_class=HTMLResponse)
async def admin_login_page(request: Request, background_tasks: BackgroundTasks):
    """관리자 로그인 및 인증 화면"""
    cookie_token = request.cookies.get("admin_token")
    if cookie_token and verify_admin_token(cookie_token):
        return RedirectResponse(url="/admin", status_code=303)
    background_tasks.add_task(record_audit, request, "admin_login")
    return templates.TemplateResponse(request=request, name="admin_login.html")


@router.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request, background_tasks: BackgroundTasks):
    """관리자용 진행 및 설정 화면 (인증된 관리자만 접근 가능)"""
    cookie_token = request.cookies.get("admin_token")
    if not cookie_token or not verify_admin_token(cookie_token):
        return RedirectResponse(url="/admin/login", status_code=303)
    background_tasks.add_task(record_audit, request, "admin")
    return templates.TemplateResponse(request=request, name="admin.html")


@router.get("/admin/logout")
async def admin_logout_page(request: Request):
    """관리자 로그아웃 처리 후 로그인 페이지로 이동 (외부 사이트 이미지 태그 등을 통한 강제 로그아웃 CSRF 방어)"""
    sec_fetch_site = request.headers.get("sec-fetch-site", "").lower()
    if sec_fetch_site not in ("cross-site",):
        cookie_token = request.cookies.get("admin_token")
        if cookie_token:
            revoke_admin_token(cookie_token)
        response = RedirectResponse(url="/admin/login", status_code=303)
        clear_admin_cookie(request, response)
        return response
    return RedirectResponse(url="/admin/login", status_code=303)




@router.api_route("/healthz", methods=["GET", "HEAD"])
@router.api_route("/api/health", methods=["GET", "HEAD"])
async def health_check(request: Request, background_tasks: BackgroundTasks):
    """
    Render 및 Supabase 활성화 유지(Keep-Alive)를 위한 헬스체크 엔드포인트.
    UptimeRobot 등의 주기적인 핑 요청 시 접속 감사 로그(access_logs)에 기록하여
    Render 인스턴스(15분 슬립 방지)와 Supabase 프로젝트를 상시 활성 상태로 유지합니다.
    """
    background_tasks.add_task(record_audit, request, "healthcheck")
    return {
        "status": "healthy",
        "service": "seoul-youth-lottery",
        "keep_alive": True,
        "client_ip": get_client_ip(request),
    }




@router.get("/logo.png")
async def get_logo():
    logo_file = BASE_DIR / "logo.png"
    if logo_file.exists():
        return FileResponse(str(logo_file), media_type="image/png")
    raise HTTPException(status_code=404, detail="Logo not found")


@router.get("/favicon.ico")
async def get_favicon():
    logo_file = BASE_DIR / "logo.png"
    if logo_file.exists():
        return FileResponse(str(logo_file), media_type="image/x-icon")
    raise HTTPException(status_code=404, detail="Favicon not found")
