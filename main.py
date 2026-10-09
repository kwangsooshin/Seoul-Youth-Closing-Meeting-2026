import os
import json
import random
import asyncio
import sqlite3
from typing import List, Dict, Any, Optional
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from dotenv import load_dotenv

# .env 로드
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin1234")

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.json"
SQLITE_PATH = BASE_DIR / "lottery.db"

import sys
# Windows cp949 콘솔 인코딩 에러 방지
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# --- 로컬 SQLite 초기화 ---
def init_sqlite():
    try:
        with sqlite3.connect(str(SQLITE_PATH)) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS draw_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    prize_rank TEXT NOT NULL,
                    prize_name TEXT DEFAULT '',
                    drawn_number INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.commit()
    except Exception as e:
        print(f"[WARN] SQLite 초기화 오류: {e}")

init_sqlite()

# Supabase 클라이언트 초기화
supabase_client = None
use_supabase = False

if SUPABASE_URL and SUPABASE_KEY and "your-project" not in SUPABASE_URL:
    try:
        from supabase import create_client
        supabase_client = create_client(SUPABASE_URL, SUPABASE_KEY)
        print("[SUCCESS] Supabase 클라이언트 연결 시도 성공")
    except Exception as e:
        print(f"[WARN] Supabase 클라이언트 초기화 실패: {e}")
else:
    print("[INFO] Supabase 설정이 없어 로컬 SQLite(lottery.db) 모드로 동작합니다.")

app = FastAPI(title="2026 Seoul Youth Policy Network General Assembly Lottery System", version="1.0.0")

# 템플릿 설정
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

# --- 설정 및 상태 관리 ---
def load_config() -> Dict[str, Any]:
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"설정 파일 읽기 오류: {e}")
    # 기본 설정
    return {
        "min_number": 1,
        "max_number": 200,
        "bgm_youtube_url": "https://www.youtube.com/watch?v=ujCh9JIxCeA",
        "prizes": [
          {"id": "prize_3", "rank": "3등", "count": 5, "name": "스타벅스 e카드 교환권"},
          {"id": "prize_2", "rank": "2등", "count": 3, "name": "무선 이어폰"},
          {"id": "prize_1", "rank": "1등", "count": 1, "name": "아이패드 10세대"}
        ]
    }

def save_config(cfg: Dict[str, Any]):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)

# 인메모리 상태 캐시
current_config = load_config()
draw_history: List[Dict[str, Any]] = []
current_pending_draw: Optional[Dict[str, Any]] = None
is_lottery_started: bool = False  # 현장 추첨 공식 시작 여부 (시작 전까지 대기 화면 및 BGM OFF)

# DB 동기화 (Supabase 우선 -> 실패/테이블부재 시 로컬 SQLite 자동 대체)
def sync_history_from_db():
    global draw_history, use_supabase
    if supabase_client:
        try:
            response = supabase_client.table("draw_history").select("*").order("created_at", desc=False).execute()
            if response.data is not None:
                draw_history = response.data
                use_supabase = True
                print(f"[SUCCESS] Supabase 'draw_history' 테이블 연동 완료 ({len(draw_history)}건 조회)")
                return
        except Exception as e:
            print(f"[INFO] Supabase 테이블 없음/조회 불가 ({e}) -> 로컬 SQLite(lottery.db)로 안전하게 자동 전환합니다.")
            use_supabase = False

    # 로컬 SQLite에서 기존 이력 조회
    try:
        with sqlite3.connect(str(SQLITE_PATH)) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT id, prize_rank, prize_name, drawn_number, status, created_at FROM draw_history ORDER BY id ASC")
            rows = cursor.fetchall()
            draw_history = [dict(row) for row in rows]
            print(f"[SUCCESS] 로컬 SQLite(lottery.db)에서 {len(draw_history)}건의 이력을 불러왔습니다.")
    except Exception as e:
        print(f"[WARN] SQLite 이력 조회 실패: {e}")

sync_history_from_db()

# DB 레코드 저장 함수
def db_save_record(record: dict) -> dict:
    global use_supabase
    if use_supabase and supabase_client:
        try:
            res = supabase_client.table("draw_history").insert(record).execute()
            if res.data:
                return res.data[0]
        except Exception as e:
            print(f"[WARN] Supabase 저장 실패 -> SQLite로 대체 저장: {e}")
            use_supabase = False

    # SQLite에 영구 저장
    try:
        with sqlite3.connect(str(SQLITE_PATH)) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO draw_history (prize_rank, prize_name, drawn_number, status)
                VALUES (?, ?, ?, ?)
            """, (record["prize_rank"], record.get("prize_name", ""), record["drawn_number"], record["status"]))
            conn.commit()
            record["id"] = cursor.lastrowid
            return record
    except Exception as e:
        print(f"[WARN] SQLite 저장 실패: {e}")
        return record

# DB 데이터 초기화 함수
def db_clear_records():
    global use_supabase
    if use_supabase and supabase_client:
        try:
            supabase_client.table("draw_history").delete().neq("id", 0).execute()
        except Exception as e:
            print(f"[WARN] Supabase 초기화 오류: {e}")

    try:
        with sqlite3.connect(str(SQLITE_PATH)) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM draw_history")
            conn.commit()
            print("[SUCCESS] 로컬 SQLite(lottery.db) 데이터가 초기화되었습니다.")
    except Exception as e:
        print(f"[WARN] SQLite 초기화 오류: {e}")


# --- WebSocket 연결 매니저 ---
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                pass

manager = ConnectionManager()


# --- 유틸리티 함수 ---
def get_used_numbers() -> set:
    """이미 확정되거나 패스된 번호 목록"""
    return {item["drawn_number"] for item in draw_history}

def get_stats():
    """현재 당첨 및 패스 현황 통계"""
    used_numbers = get_used_numbers()
    total_range = current_config["max_number"] - current_config["min_number"] + 1
    remaining_pool_count = max(0, total_range - len(used_numbers))

    confirmed_by_rank: Dict[str, List[int]] = {}
    passed_numbers: List[Dict[str, Any]] = []

    for item in draw_history:
        rank = item["prize_rank"]
        num = item["drawn_number"]
        if item["status"] == "CONFIRMED":
            if rank not in confirmed_by_rank:
                confirmed_by_rank[rank] = []
            confirmed_by_rank[rank].append(num)
        elif item["status"] == "PASSED":
            passed_numbers.append(item)

    # 등수별 진행률
    prize_status = []
    for p in current_config["prizes"]:
        rank_name = p["rank"]
        confirmed_count = len(confirmed_by_rank.get(rank_name, []))
        prize_status.append({
            "rank": rank_name,
            "name": p.get("name", ""),
            "target_count": p["count"],
            "confirmed_count": confirmed_count,
            "confirmed_numbers": confirmed_by_rank.get(rank_name, []),
            "is_completed": confirmed_count >= p["count"]
        })

    return {
        "config": current_config,
        "history": draw_history,
        "prize_status": prize_status,
        "passed_numbers": passed_numbers,
        "used_numbers": list(used_numbers),
        "total_tickets": total_range,
        "remaining_pool_count": remaining_pool_count,
        "current_pending_draw": current_pending_draw,
        "is_lottery_started": is_lottery_started,
        "db_info": {
            "type": "SUPABASE" if use_supabase else "SQLITE",
            "name": "Supabase 클라우드" if use_supabase else "로컬 SQLite (lottery.db)",
            "details": f"테이블: draw_history ({len(draw_history)}건)" if use_supabase else f"파일: lottery.db ({len(draw_history)}건)"
        }
    }


# --- 정적 자산 라우트 (로고 및 파비콘) ---
@app.get("/logo.png")
async def get_logo():
    logo_file = BASE_DIR / "logo.png"
    if logo_file.exists():
        return FileResponse(str(logo_file), media_type="image/png")
    raise HTTPException(status_code=404, detail="Logo not found")

@app.get("/favicon.ico")
async def get_favicon():
    logo_file = BASE_DIR / "logo.png"
    if logo_file.exists():
        return FileResponse(str(logo_file), media_type="image/png")
    raise HTTPException(status_code=404, detail="Favicon not found")


# --- 웹 페이지 라우트 ---
@app.get("/", response_class=HTMLResponse)
async def display_page(request: Request):
    """현장 송출용 화면 (대형 스크린 / 관객용)"""
    return templates.TemplateResponse(request=request, name="display.html")

@app.get("/display", response_class=HTMLResponse)
async def display_alias(request: Request):
    return templates.TemplateResponse(request=request, name="display.html")

@app.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request):
    """관리자용 진행 및 설정 화면"""
    return templates.TemplateResponse(request=request, name="admin.html")


# --- WebSocket 엔드포인트 ---
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    # 첫 연결 시 현재 전체 상태 전송
    try:
        await websocket.send_json({"type": "SYNC_STATE", "data": get_stats()})
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception:
        manager.disconnect(websocket)


# --- REST API 엔드포인트 ---

class VerifyPasswordRequest(BaseModel):
    password: str

@app.post("/api/admin/verify")
async def verify_admin(req: VerifyPasswordRequest):
    if req.password == ADMIN_PASSWORD:
        return {"success": True}
    raise HTTPException(status_code=401, detail="비밀번호가 올바르지 않습니다.")

@app.get("/api/state")
async def get_state():
    return get_stats()

class ConfigUpdateRequest(BaseModel):
    password: str
    min_number: int
    max_number: int
    bgm_youtube_url: Optional[str] = "https://www.youtube.com/watch?v=ujCh9JIxCeA"
    prizes: List[Dict[str, Any]]

@app.post("/api/config")
async def update_config(req: ConfigUpdateRequest):
    if req.password != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="인증 실패")

    if req.min_number >= req.max_number:
        raise HTTPException(status_code=400, detail="최소 번호는 최대 번호보다 작아야 합니다.")

    global current_config
    current_config = {
        "min_number": req.min_number,
        "max_number": req.max_number,
        "bgm_youtube_url": req.bgm_youtube_url or "https://www.youtube.com/watch?v=ujCh9JIxCeA",
        "prizes": req.prizes
    }
    save_config(current_config)

    # 상태 브로드캐스트
    state = get_stats()
    await manager.broadcast({"type": "CONFIG_UPDATED", "data": state})
    return {"success": True, "config": current_config}


class BgmControlRequest(BaseModel):
    password: str
    action: str  # "play", "pause", "mute", "unmute", "set_volume"
    volume: Optional[int] = 30

@app.post("/api/bgm/control")
async def control_bgm(req: BgmControlRequest):
    if req.password != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="인증 실패")

    await manager.broadcast({
        "type": "BGM_CONTROL",
        "action": req.action,
        "volume": req.volume
    })
    return {"success": True, "action": req.action, "volume": req.volume}


class LotterySessionRequest(BaseModel):
    password: str
    started: bool

@app.post("/api/draw/session")
async def set_lottery_session(req: LotterySessionRequest):
    """현장 추첨 이벤트 시작 및 대기 모드 전환"""
    global is_lottery_started
    if req.password != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="인증 실패")

    is_lottery_started = req.started
    state = get_stats()
    await manager.broadcast({
        "type": "LOTTERY_SESSION_STATE",
        "started": is_lottery_started,
        "data": state
    })
    return {"success": True, "started": is_lottery_started}


class DrawStartRequest(BaseModel):
    password: str
    rank: str
    name: Optional[str] = ""

@app.post("/api/draw/start")
async def start_draw(req: DrawStartRequest):
    global current_pending_draw
    if req.password != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="인증 실패")

    if current_pending_draw is not None:
        return {"success": False, "message": "이미 진행 중인 추첨 번호가 있습니다. 확정 또는 패스를 먼저 처리하세요.", "current": current_pending_draw}

    used_numbers = get_used_numbers()
    min_num = current_config["min_number"]
    max_num = current_config["max_number"]

    available_numbers = [n for n in range(min_num, max_num + 1) if n not in used_numbers]

    if not available_numbers:
        raise HTTPException(status_code=400, detail="추첨 가능한 남은 번호가 없습니다!")

    picked_number = random.choice(available_numbers)
    current_pending_draw = {
        "number": picked_number,
        "prize_rank": req.rank,
        "prize_name": req.name or "",
        "status": "DRAWING"
    }

    # 브로드캐스트: 추첨 롤링 시작 이벤트
    await manager.broadcast({
        "type": "DRAW_ROLLING_START",
        "data": current_pending_draw
    })

    return {"success": True, "picked_number": picked_number, "data": current_pending_draw}


class DrawActionRequest(BaseModel):
    password: str

@app.post("/api/draw/confirm")
async def confirm_draw(req: DrawActionRequest):
    """현재 번호 당첨 확정"""
    global current_pending_draw, draw_history
    if req.password != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="인증 실패")

    if not current_pending_draw:
        raise HTTPException(status_code=400, detail="확정할 추첨 번호가 없습니다.")

    record = {
        "prize_rank": current_pending_draw["prize_rank"],
        "prize_name": current_pending_draw["prize_name"],
        "drawn_number": current_pending_draw["number"],
        "status": "CONFIRMED"
    }

    # DB 저장 (Supabase 우선, 실패/미연결 시 로컬 SQLite 자동 저장)
    record = db_save_record(record)
    draw_history.append(record)
    confirmed_item = dict(current_pending_draw)
    current_pending_draw = None

    state = get_stats()
    await manager.broadcast({
        "type": "DRAW_CONFIRMED",
        "item": confirmed_item,
        "data": state
    })

    return {"success": True, "record": record}


@app.post("/api/draw/pass")
async def pass_draw(req: DrawActionRequest):
    """호명 시 부재자 패스 처리 (넘어가기)"""
    global current_pending_draw, draw_history
    if req.password != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="인증 실패")

    if not current_pending_draw:
        raise HTTPException(status_code=400, detail="패스할 추첨 번호가 없습니다.")

    record = {
        "prize_rank": current_pending_draw["prize_rank"],
        "prize_name": current_pending_draw["prize_name"],
        "drawn_number": current_pending_draw["number"],
        "status": "PASSED"
    }

    # DB 저장 (Supabase 우선, 실패/미연결 시 로컬 SQLite 자동 저장)
    record = db_save_record(record)
    draw_history.append(record)
    passed_item = dict(current_pending_draw)
    current_pending_draw = None

    state = get_stats()
    await manager.broadcast({
        "type": "DRAW_PASSED",
        "item": passed_item,
        "data": state
    })

    return {"success": True, "record": record}


class DrawResetRequest(BaseModel):
    password: str

@app.post("/api/draw/reset")
async def reset_draw(req: DrawResetRequest):
    """추첨 이력 전체 초기화"""
    global current_pending_draw, draw_history, is_lottery_started
    if req.password != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="인증 실패")

    # DB 초기화 (Supabase 및 로컬 SQLite 모두 초기화)
    db_clear_records()

    draw_history = []
    current_pending_draw = None
    is_lottery_started = False

    state = get_stats()
    await manager.broadcast({
        "type": "DRAW_RESET",
        "data": state
    })

    return {"success": True}
