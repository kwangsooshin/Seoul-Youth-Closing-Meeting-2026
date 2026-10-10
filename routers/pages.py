from fastapi import APIRouter, Request, HTTPException, BackgroundTasks
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.templating import Jinja2Templates
from core.config import BASE_DIR
from db import save_access_log

router = APIRouter(tags=["Pages"])

templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def get_client_ip(request: Request) -> str:
    """프록시/클라우드 환경(X-Forwarded-For 등) 및 로컬 환경에서 클라이언트 IP 추출"""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        parts = [p.strip() for p in forwarded.split(",") if p.strip()]
        if parts:
            return parts[0]

    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip.strip()

    cf_ip = request.headers.get("cf-connecting-ip")
    if cf_ip:
        return cf_ip.strip()

    if request.client and request.client.host:
        return request.client.host

    return "unknown"


def record_audit(request: Request, page_type: str):
    """페이지 접속 감사 로그(Audit Log)를 백그라운드로 안전하게 DB 저장"""
    try:
        ip = get_client_ip(request)
        path = request.url.path
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


@router.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request, background_tasks: BackgroundTasks):
    """관리자용 진행 및 설정 화면"""
    background_tasks.add_task(record_audit, request, "admin")
    return templates.TemplateResponse(request=request, name="admin.html")


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
        return FileResponse(str(logo_file), media_type="image/png")
    raise HTTPException(status_code=404, detail="Favicon not found")
