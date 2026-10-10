import os
import json
import secrets
import asyncio
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

ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin1234")

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.json"

DEFAULT_BGM_URL = "https://www.youtube.com/watch?v=ujCh9JIxCeA"

# config.json 기본값 (파일이 없거나 손상되어도 이 값으로 동작)
DEFAULT_CONFIG: Dict[str, Any] = {
    "min_number": 1,
    "max_number": 200,
    "bgm_youtube_url": DEFAULT_BGM_URL,
}

# prizes 테이블이 비어 있을 때 최초 1회 시드되는 기본 등수
DEFAULT_PRIZES: List[Dict[str, Any]] = [
    {"rank": "3등", "count": 5, "name": "스타벅스 e카드 교환권"},
    {"rank": "2등", "count": 3, "name": "무선 이어폰"},
    {"rank": "1등", "count": 1, "name": "아이패드 10세대"},
]

import sys
# Windows cp949 콘솔 인코딩 에러 방지
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# --- DB 모듈 임포트 및 초기화 ---
from db import init_db, load_prizes, load_history, save_prizes, save_record, delete_last_record, clear_records, get_db_info

init_db(DEFAULT_PRIZES)

app = FastAPI(title="2026 Seoul Youth Policy Network General Assembly Lottery System", version="1.0.0")

# 템플릿 설정
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

# --- 설정 및 상태 관리 ---
def load_config() -> Dict[str, Any]:
    """config.json은 읽기 전용 기본값 파일. 없거나 손상되어도 DEFAULT_CONFIG로 동작한다.
    관리자 페이지에서 변경한 값은 메모리에만 반영되며 파일에 기록하지 않는다."""
    cfg = dict(DEFAULT_CONFIG)
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            for key in DEFAULT_CONFIG:
                if key in data:
                    cfg[key] = data[key]
        except Exception as e:
            print(f"설정 파일 읽기 오류 (기본값 사용): {e}")
    return cfg

# 인메모리 상태 캐시
current_config = load_config()
current_prizes: List[Dict[str, Any]] = []
draw_history: List[Dict[str, Any]] = []
current_pending_draw: Optional[Dict[str, Any]] = None
is_lottery_started: bool = False  # 현장 추첨 공식 시작 여부 (시작 전까지 대기 화면 및 BGM OFF)

def sync_from_db():
    global current_prizes, draw_history
    try:
        current_prizes = load_prizes()
        draw_history = load_history()
        info = get_db_info(len(draw_history))
        print(f"[SUCCESS] {info['name']}에서 등수 {len(current_prizes)}개, 이력 {len(draw_history)}건을 불러왔습니다.")
    except Exception as e:
        print(f"[WARN] DB 조회 실패: {e}")

sync_from_db()


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

def find_prize(prize_id: int) -> Optional[Dict[str, Any]]:
    return next((p for p in current_prizes if p["id"] == prize_id), None)

def get_stats():
    """현재 당첨 및 패스 현황 통계"""
    used_numbers = get_used_numbers()
    total_range = current_config["max_number"] - current_config["min_number"] + 1
    remaining_pool_count = max(0, total_range - len(used_numbers))

    confirmed_by_prize: Dict[int, List[int]] = {}
    passed_numbers: List[Dict[str, Any]] = []

    for item in draw_history:
        if item["status"] == "CONFIRMED":
            confirmed_by_prize.setdefault(item["prize_id"], []).append(item["drawn_number"])
        elif item["status"] == "PASSED":
            passed_numbers.append(item)

    # 등수별 진행률
    prize_status = []
    for p in current_prizes:
        confirmed = confirmed_by_prize.get(p["id"], [])
        prize_status.append({
            "id": p["id"],
            "rank": p["rank"],
            "name": p.get("name", ""),
            "target_count": p["count"],
            "confirmed_count": len(confirmed),
            "confirmed_numbers": confirmed,
            "is_completed": len(confirmed) >= p["count"]
        })

    return {
        "config": {**current_config, "prizes": current_prizes},
        "history": draw_history,
        "prize_status": prize_status,
        "passed_numbers": passed_numbers,
        "used_numbers": list(used_numbers),
        "total_tickets": total_range,
        "remaining_pool_count": remaining_pool_count,
        "current_pending_draw": current_pending_draw,
        "is_lottery_started": is_lottery_started,
        "db_info": get_db_info(len(draw_history))
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
            text = await websocket.receive_text()
            try:
                data = json.loads(text)
                if isinstance(data, dict) and data.get("type"):
                    await manager.broadcast(data)
            except Exception:
                pass
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

class PrizeInput(BaseModel):
    id: Optional[int] = None
    rank: str
    count: int
    name: Optional[str] = ""

class ConfigUpdateRequest(BaseModel):
    password: str
    min_number: int
    max_number: int
    bgm_youtube_url: Optional[str] = DEFAULT_BGM_URL
    prizes: Optional[List[PrizeInput]] = None  # None이면 등수 설정은 변경하지 않음

@app.post("/api/config")
async def update_config(req: ConfigUpdateRequest):
    global current_config, current_prizes, draw_history
    if req.password != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="인증 실패")

    if req.min_number >= req.max_number:
        raise HTTPException(status_code=400, detail="최소 번호는 최대 번호보다 작아야 합니다.")

    # 등수(prizes) 변경 -> DB 반영
    if req.prizes is not None:
        prizes = [
            {"id": p.id, "rank": p.rank.strip(), "count": p.count, "name": (p.name or "").strip()}
            for p in req.prizes
            if p.rank.strip() and p.count > 0
        ]
        if not prizes:
            raise HTTPException(status_code=400, detail="최소 1개 이상의 등수를 설정해야 합니다.")

        # 이력/진행 중 추첨에서 참조 중인 등수는 삭제 불가
        incoming_ids = {p["id"] for p in prizes if p["id"] is not None}
        in_use_ids = {h["prize_id"] for h in draw_history}
        if current_pending_draw:
            in_use_ids.add(current_pending_draw["prize_id"])
        blocked = [p["rank"] for p in current_prizes if p["id"] in in_use_ids and p["id"] not in incoming_ids]
        if blocked:
            raise HTTPException(
                status_code=400,
                detail=f"추첨 이력이 있는 등수는 삭제할 수 없습니다: {', '.join(blocked)} (이력 초기화 후 삭제하세요)",
            )

        try:
            save_prizes(prizes, current_prizes)
            current_prizes = load_prizes()
            draw_history = load_history()  # 등수명 변경을 이력(JOIN)에 반영
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"등수 저장 실패: {e}")

    # 번호 범위 / BGM 은 메모리에만 반영 (config.json 은 수정하지 않음)
    current_config = {
        "min_number": req.min_number,
        "max_number": req.max_number,
        "bgm_youtube_url": req.bgm_youtube_url or DEFAULT_BGM_URL,
    }

    # 상태 브로드캐스트
    state = get_stats()
    await manager.broadcast({"type": "CONFIG_UPDATED", "data": state})
    return {"success": True, "config": state["config"]}


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
    prize_id: int

@app.post("/api/draw/start")
async def start_draw(req: DrawStartRequest):
    global current_pending_draw
    if req.password != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="인증 실패")

    if not is_lottery_started:
        raise HTTPException(status_code=400, detail="현장 추첨이 아직 공식 시작되지 않았습니다. 먼저 '현장 추첨 공식 시작' 버튼을 눌러주세요.")

    if current_pending_draw is not None:
        return {"success": False, "message": "이미 진행 중인 추첨 번호가 있습니다. 확정 또는 패스를 먼저 처리하세요.", "current": current_pending_draw}

    prize = find_prize(req.prize_id)
    if not prize:
        raise HTTPException(status_code=400, detail="존재하지 않는 등수입니다. 새로고침 후 다시 시도하세요.")

    used_numbers = get_used_numbers()
    min_num = current_config["min_number"]
    max_num = current_config["max_number"]

    available_numbers = [n for n in range(min_num, max_num + 1) if n not in used_numbers]

    if not available_numbers:
        raise HTTPException(status_code=400, detail="추첨 가능한 남은 번호가 없습니다!")

    picked_number = secrets.choice(available_numbers)
    current_pending_draw = {
        "number": picked_number,
        "prize_id": prize["id"],
        "prize_rank": prize["rank"],
        "prize_name": prize["name"],
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

async def _finalize_pending_draw(status: str, event_type: str):
    """진행 중인 추첨을 확정(CONFIRMED) 또는 패스(PASSED)로 기록"""
    global current_pending_draw, draw_history
    record = {
        "prize_id": current_pending_draw["prize_id"],
        "drawn_number": current_pending_draw["number"],
        "status": status
    }

    # DB 저장 (Supabase 우선, 실패/미연결 시 로컬 SQLite 자동 저장) -> prizes JOIN 결과 반환
    try:
        record = save_record(record, current_prizes)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"기록 저장 실패: {e}")
    draw_history.append(record)
    item = dict(current_pending_draw)
    current_pending_draw = None

    state = get_stats()
    await manager.broadcast({
        "type": event_type,
        "item": item,
        "data": state
    })
    return {"success": True, "record": record}

@app.post("/api/draw/confirm")
async def confirm_draw(req: DrawActionRequest):
    """현재 번호 당첨 확정"""
    if req.password != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="인증 실패")

    if not current_pending_draw:
        raise HTTPException(status_code=400, detail="확정할 추첨 번호가 없습니다.")

    return await _finalize_pending_draw("CONFIRMED", "DRAW_CONFIRMED")


@app.post("/api/draw/pass")
async def pass_draw(req: DrawActionRequest):
    """호명 시 부재자 패스 처리 (넘어가기)"""
    if req.password != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="인증 실패")

    if not current_pending_draw:
        raise HTTPException(status_code=400, detail="패스할 추첨 번호가 없습니다.")

@app.post("/api/draw/cancel-last")
async def cancel_last_draw(req: DrawActionRequest):
    """방금 확정/패스된 가장 최근 추첨 건 취소 및 롤백"""
    global draw_history
    if req.password != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="인증 실패")

    if not is_lottery_started:
        raise HTTPException(status_code=400, detail="현장 추첨이 시작되지 않은 대기 상태에서는 취소할 수 없습니다.")

    if not draw_history:
        raise HTTPException(status_code=400, detail="취소할 수 있는 최근 추첨 내역이 없습니다.")

    last_record = draw_history[-1]
    deleted_id = delete_last_record()
    if not deleted_id:
        raise HTTPException(status_code=500, detail="DB에서 최근 내역을 삭제하지 못했습니다.")

    removed_item = draw_history.pop()
    state = get_stats()

    await manager.broadcast({
        "type": "DRAW_CANCELLED",
        "item": removed_item,
        "data": state
    })

    return {"success": True, "cancelled": removed_item}


class DrawResetRequest(BaseModel):
    password: str

@app.post("/api/draw/reset")
async def reset_draw(req: DrawResetRequest):
    """추첨 이력 전체 초기화"""
    global current_pending_draw, draw_history, is_lottery_started
    if req.password != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="인증 실패")

    # DB 초기화 (Supabase 및 로컬 SQLite 모두 초기화)
    clear_records()

    draw_history = []
    current_pending_draw = None
    is_lottery_started = False

    state = get_stats()
    await manager.broadcast({
        "type": "DRAW_RESET",
        "data": state
    })

    return {"success": True}
