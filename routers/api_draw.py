import secrets
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from core.config import ADMIN_PASSWORD
from core.state import state
from core.websocket import manager
from db import save_record, delete_last_record, clear_records

router = APIRouter(prefix="/api/draw", tags=["Draw"])


class LotterySessionRequest(BaseModel):
    password: str
    started: bool


@router.post("/session")
async def set_lottery_session(req: LotterySessionRequest):
    """현장 추첨 이벤트 시작 및 대기 모드 전환"""
    if req.password != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="인증 실패")

    state.is_started = req.started
    stats = state.get_stats()
    await manager.broadcast({
        "type": "LOTTERY_SESSION_STATE",
        "started": state.is_started,
        "data": stats
    })
    return {"success": True, "started": state.is_started}


class DrawStartRequest(BaseModel):
    password: str
    prize_id: int


@router.post("/start")
async def start_draw(req: DrawStartRequest):
    if req.password != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="인증 실패")

    if not state.is_started:
        raise HTTPException(status_code=400, detail="현재 대기화면 상태입니다. 먼저 '대기화면 해제'를 해주세요.")

    if state.pending_draw is not None:
        return {"success": False, "message": "이미 진행 중인 추첨 번호가 있습니다. 확정 또는 패스를 먼저 처리하세요.", "current": state.pending_draw}

    prize = state.find_prize(req.prize_id)
    if not prize:
        raise HTTPException(status_code=400, detail="존재하지 않는 등수입니다. 새로고침 후 다시 시도하세요.")

    used_numbers = state.get_used_numbers()
    min_num = state.config["min_number"]
    max_num = state.config["max_number"]

    available_numbers = [n for n in range(min_num, max_num + 1) if n not in used_numbers]

    if not available_numbers:
        raise HTTPException(status_code=400, detail="추첨 가능한 남은 번호가 없습니다!")

    picked_number = secrets.choice(available_numbers)
    state.pending_draw = {
        "number": picked_number,
        "prize_id": prize["id"],
        "prize_rank": prize["rank"],
        "prize_name": prize["name"],
        "status": "DRAWING"
    }

    # 브로드캐스트: 추첨 롤링 시작 이벤트
    await manager.broadcast({
        "type": "DRAW_ROLLING_START",
        "data": state.pending_draw
    })

    return {"success": True, "picked_number": picked_number, "data": state.pending_draw}


class DrawActionRequest(BaseModel):
    password: str


async def _finalize_pending_draw(status: str, event_type: str):
    """진행 중인 추첨을 확정(CONFIRMED) 또는 패스(PASSED)로 기록"""
    record = {
        "prize_id": state.pending_draw["prize_id"],
        "drawn_number": state.pending_draw["number"],
        "status": status
    }

    # DB 저장 (Supabase 우선, 실패/미연결 시 로컬 SQLite 자동 저장) -> prizes JOIN 결과 반환
    try:
        record = save_record(record, state.prizes)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"기록 저장 실패: {e}")

    state.history.append(record)
    item = dict(state.pending_draw)
    state.pending_draw = None

    stats = state.get_stats()
    await manager.broadcast({
        "type": event_type,
        "item": item,
        "data": stats
    })
    return {"success": True, "record": record}


@router.post("/confirm")
async def confirm_draw(req: DrawActionRequest):
    """현재 번호 당첨 확정"""
    if req.password != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="인증 실패")

    if not state.pending_draw:
        raise HTTPException(status_code=400, detail="확정할 추첨 번호가 없습니다.")

    return await _finalize_pending_draw("CONFIRMED", "DRAW_CONFIRMED")


@router.post("/pass")
async def pass_draw(req: DrawActionRequest):
    """호명 시 부재자 패스 처리 (넘어가기)"""
    if req.password != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="인증 실패")

    if not state.pending_draw:
        raise HTTPException(status_code=400, detail="패스할 추첨 번호가 없습니다.")

    return await _finalize_pending_draw("PASSED", "DRAW_PASSED")


@router.post("/cancel-last")
async def cancel_last_draw(req: DrawActionRequest):
    """방금 확정/패스된 가장 최근 추첨 건 취소 및 롤백"""
    if req.password != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="인증 실패")

    if not state.is_started:
        raise HTTPException(status_code=400, detail="현재 대기화면 상태에서는 취소할 수 없습니다. 먼저 '대기화면 해제'를 해주세요.")

    if not state.history:
        raise HTTPException(status_code=400, detail="취소할 수 있는 최근 추첨 내역이 없습니다.")

    deleted_id = delete_last_record()
    if not deleted_id:
        raise HTTPException(status_code=500, detail="DB에서 최근 내역을 삭제하지 못했습니다.")

    removed_item = state.history.pop()
    stats = state.get_stats()

    await manager.broadcast({
        "type": "DRAW_CANCELLED",
        "item": removed_item,
        "data": stats
    })

    return {"success": True, "cancelled": removed_item}


class DrawResetRequest(BaseModel):
    password: str


@router.post("/reset")
async def reset_draw(req: DrawResetRequest):
    """추첨 이력 전체 초기화"""
    if req.password != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="인증 실패")

    # DB 초기화 (Supabase 및 로컬 SQLite 모두 초기화)
    clear_records()

    state.history = []
    state.pending_draw = None
    state.is_started = False

    stats = state.get_stats()
    await manager.broadcast({
        "type": "DRAW_RESET",
        "data": stats
    })

    return {"success": True}
