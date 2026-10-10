from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from core.config import DEFAULT_PRIZES, BASE_DIR
from core.state import state
from db import init_db
from routers import pages, websocket, api_admin, api_draw

# --- 데이터베이스 초기화 및 인메모리 상태 로드 ---
init_db(DEFAULT_PRIZES)
state.sync_from_db()

# --- FastAPI 애플리케이션 생성 ---
app = FastAPI(
    title="2026 Seoul Youth Policy Network General Assembly Lottery System",
    version="1.0.0"
)

# 정적 파일 마운트 (static 폴더 존재 시)
static_dir = BASE_DIR / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

# --- 모듈별 라우터 등록 ---
app.include_router(pages.router)
app.include_router(websocket.router)
app.include_router(api_admin.router)
app.include_router(api_draw.router)
