from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.templating import Jinja2Templates
from core.config import BASE_DIR

router = APIRouter(tags=["Pages"])

templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


@app_router_root := router.get("/", response_class=HTMLResponse)
async def display_page(request: Request):
    """현장 송출용 화면 (대형 스크린 / 관객용)"""
    return templates.TemplateResponse(request=request, name="display.html")


@router.get("/display", response_class=HTMLResponse)
async def display_alias(request: Request):
    return templates.TemplateResponse(request=request, name="display.html")


@router.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request):
    """관리자용 진행 및 설정 화면"""
    return templates.TemplateResponse(request=request, name="admin.html")


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
