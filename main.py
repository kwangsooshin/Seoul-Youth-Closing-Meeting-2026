import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from core.config import DEFAULT_PRIZES, DEFAULT_CONFIG, BASE_DIR
from core.state import state
from db import init_db, cleanup_old_access_logs
from routers import pages, websocket, api_admin, api_draw

# --- 데이터베이스 초기화 및 인메모리 상태 로드 ---
init_db(DEFAULT_PRIZES, DEFAULT_CONFIG)
state.sync_from_db()


async def access_logs_cleanup_loop(interval_seconds: int = 3600):
    """FastAPI 백그라운드 스케줄러: 1시간마다 24시간 지난 오래된 access_logs 자동 정리"""
    print("[SCHEDULER] access_logs 백그라운드 자동 정리 스케줄러 가동 (주기: 1시간, 보관: 최근 24시간)")
    while True:
        try:
            cleanup_old_access_logs(hours=24)
        except Exception as e:
            print(f"[WARN] access_logs 백그라운드 정리 오류: {e}")
        await asyncio.sleep(interval_seconds)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. 서버 시작 시 스케줄러 시작
    cleanup_task = asyncio.create_task(access_logs_cleanup_loop(interval_seconds=3600))
    yield
    # 2. 서버 종료 시 안전하게 정리
    cleanup_task.cancel()
    try:
        await cleanup_task
    except asyncio.CancelledError:
        pass
    print("[SCHEDULER] access_logs 백그라운드 스케줄러 종료")


# --- FastAPI 애플리케이션 생성 ---
app = FastAPI(
    title="2026 Seoul Youth Policy Network General Assembly Lottery System",
    version="1.0.0",
    lifespan=lifespan
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
