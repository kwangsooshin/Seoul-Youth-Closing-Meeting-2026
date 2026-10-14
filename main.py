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


import time
from core.websocket import manager

async def access_logs_cleanup_loop(interval_seconds: int = 3600):
    """FastAPI 백그라운드 스케줄러: 1시간마다 24시간 지난 오래된 access_logs 자동 정리"""
    print("[SCHEDULER] access_logs 백그라운드 자동 정리 스케줄러 가동 (주기: 1시간, 보관: 최근 24시간)")
    while True:
        try:
            cleanup_old_access_logs(hours=24)
        except Exception as e:
            print(f"[WARN] access_logs 백그라운드 정리 오류: {e}")
        await asyncio.sleep(interval_seconds)


async def session_timeout_safety_loop(interval_seconds: int = 60):
    """FastAPI 백그라운드 스케줄러: 관리자 세션 무갱신 3시간 지속 만료 감시 (대기화면 복귀 및 BGM 종료)"""
    while True:
        try:
            now = time.time()
            last_active = state.session_last_active_at or state.session_started_at
            if state.is_started and last_active and (now - last_active >= 3 * 3600):
                print("[SCHEDULER] 관리자 세션 갱신 없이 3시간 경과 감지: 대기화면 복귀 및 BGM 종료 실행")
                state.stop_session()
                state.audio_state["bgm_paused"] = True
                stats = state.get_stats()
                await manager.broadcast({
                    "type": "LOTTERY_SESSION_STATE",
                    "started": False,
                    "auto_timeout": True,
                    "data": stats
                })
                await manager.broadcast({
                    "type": "BGM_CONTROL",
                    "action": "stop",
                    "audio_state": state.audio_state
                })
        except Exception as e:
            print(f"[WARN] 세션 만료 감시 오류: {e}")
        await asyncio.sleep(interval_seconds)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. 서버 시작 시 스케줄러 시작
    cleanup_task = asyncio.create_task(access_logs_cleanup_loop(interval_seconds=3600))
    session_guard_task = asyncio.create_task(session_timeout_safety_loop(interval_seconds=60))
    yield
    # 2. 서버 종료 시 안전하게 정리
    cleanup_task.cancel()
    session_guard_task.cancel()
    try:
        await cleanup_task
    except asyncio.CancelledError:
        pass
    try:
        await session_guard_task
    except asyncio.CancelledError:
        pass
    print("[SCHEDULER] 백그라운드 스케줄러 종료")


# --- FastAPI 애플리케이션 생성 ---
app = FastAPI(
    title="2026 Seoul Youth Policy Network General Assembly Lottery System",
    version="1.0.0",
    lifespan=lifespan
)


@app.middleware("http")
async def add_security_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response

# 정적 파일 마운트 (static 폴더 존재 시)
static_dir = BASE_DIR / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

# --- 모듈별 라우터 등록 ---
app.include_router(pages.router)
app.include_router(websocket.router)
app.include_router(api_admin.router)
app.include_router(api_draw.router)
