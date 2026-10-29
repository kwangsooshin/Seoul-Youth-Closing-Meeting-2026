import asyncio
import secrets
import time
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from core.state import state
from core.websocket import manager
from core.auth import require_admin
from db import save_record, delete_last_record, clear_records

router = APIRouter(
    prefix="/api/draw",
    tags=["Draw"],
    dependencies=[Depends(require_admin)],
)


class LotterySessionRequest(BaseModel):
    started: bool


class PrizeIdRequest(BaseModel):
    prize_id: int


@router.post("/session")
async def set_lottery_session(req: LotterySessionRequest):
    """현장 추첨 이벤트 시작 및 대기 모드 전환 (세션 무조작 안전 만료는 백그라운드 스케줄러가 관리)"""
    async with state.lock:
        if req.started:
            state.start_session()
            print("[SESSION] 추첨 세션 시작: 대기화면 해제")
        else:
            state.stop_session()
            print("[SESSION] 추첨 세션 중지: 대기화면 표시 전환")

        stats = state.get_stats()
        started = state.is_started
        started_at = state.session_started_at
        last_active_at = state.session_last_active_at
        audio_state = dict(state.audio_state)

    await manager.broadcast({
        "type": "LOTTERY_SESSION_STATE",
        "started": started,
        "auto_timeout": False,
        "data": stats
    })
    return {
        "success": True,
        "started": started,
        "session_started_at": started_at,
        "session_last_active_at": last_active_at,
        "audio_state": audio_state
    }


@router.post("/select-prize")
async def select_prize(req: PrizeIdRequest):
    """관리자 콘솔에서 추첨할 등수 선택 변경 시 디스플레이와 실시간 동기화"""
    async with state.lock:
        prize = state.find_prize(req.prize_id)
        if not prize:
            raise HTTPException(status_code=400, detail="존재하지 않는 등수입니다.")

        state.selected_prize_id = req.prize_id
        stats = state.get_stats()

    await manager.broadcast({
        "type": "PRIZE_TARGET_CHANGED",
        "prize_id": prize["id"],
        "rank": prize["rank"],
        "name": prize.get("name", ""),
        "data": stats
    })
    return {
        "success": True,
        "prize_id": req.prize_id,
        "rank": prize["rank"],
        "name": prize.get("name", "")
    }


@router.post("/start")
async def start_draw(req: PrizeIdRequest):
    async with state.lock:
        if not state.is_started:
            raise HTTPException(status_code=400, detail="현재 대기화면 상태입니다. 먼저 '대기화면 해제'를 해주세요.")

        if state.pending_draw is not None:
            raise HTTPException(status_code=400, detail="이미 진행 중인 추첨 번호가 있습니다. 확정 또는 패스를 먼저 처리하세요.")

        prize = state.find_prize(req.prize_id)
        if not prize:
            raise HTTPException(status_code=400, detail="존재하지 않는 등수입니다. 새로고침 후 다시 시도하세요.")

        state.selected_prize_id = req.prize_id

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
            "status": "DRAWING",
            "drawn_at": time.time(),
            "rolling_completed": False,
        }
        payload = {
            "number": picked_number,
            "prize_id": prize["id"],
            "prize_rank": prize["rank"],
            "prize_name": prize["name"],
            "status": "DRAWING",
        }

    # 브로드캐스트: 추첨 롤링 시작 이벤트
    await manager.broadcast({
        "type": "DRAW_ROLLING_START",
        "data": payload
    })

    return {"success": True, "picked_number": picked_number, "data": payload}


async def _finalize_pending_draw(status: str, event_type: str, empty_error_msg: str):
    """진행 중인 추첨을 확정(CONFIRMED) 또는 패스(PASSED)로 기록"""
    async with state.lock:
        if not state.pending_draw:
            raise HTTPException(status_code=400, detail=empty_error_msg)

        record_input = {
            "prize_id": state.pending_draw["prize_id"],
            "drawn_number": state.pending_draw["number"],
            "status": status
        }

        try:
            record = await asyncio.to_thread(save_record, record_input, state.prizes)
        except Exception as e:
            print(f"[ERROR] 추첨 기록 저장 실패: {e}")
            raise HTTPException(status_code=500, detail="추첨 기록을 저장하는 중 서버 오류가 발생했습니다.")

        state.history.append(record)
        item = {
            "number": state.pending_draw["number"],
            "prize_id": state.pending_draw["prize_id"],
            "prize_rank": state.pending_draw["prize_rank"],
            "prize_name": state.pending_draw["prize_name"],
            "status": state.pending_draw["status"],
        }
        state.pending_draw = None
        stats = state.get_stats()

    await manager.broadcast({
        "type": event_type,
        "item": item,
        "data": stats
    })
    return {"success": True, "record": record}


@router.post("/confirm")
async def confirm_draw():
    """현재 번호 당첨 확정"""
    return await _finalize_pending_draw("CONFIRMED", "DRAW_CONFIRMED", "확정할 추첨 번호가 없습니다.")


@router.post("/pass")
async def pass_draw():
    """호명 시 부재자 패스 처리 (넘어가기)"""
    return await _finalize_pending_draw("PASSED", "DRAW_PASSED", "패스할 추첨 번호가 없습니다.")


@router.post("/cancel-last")
async def cancel_last_draw():
    """방금 확정/패스된 가장 최근 추첨 건 취소 및 롤백"""
    async with state.lock:
        if not state.is_started:
            raise HTTPException(status_code=400, detail="현재 대기화면 상태에서는 취소할 수 없습니다. 먼저 '대기화면 해제'를 해주세요.")

        if state.pending_draw is not None:
            raise HTTPException(status_code=400, detail="진행 중인 추첨이 있습니다. 먼저 확정 또는 패스를 처리하세요.")

        if not state.history:
            raise HTTPException(status_code=400, detail="취소할 수 있는 최근 추첨 내역이 없습니다.")

        deleted_id = await asyncio.to_thread(delete_last_record)
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


@router.post("/reset")
async def reset_draw():
    """추첨 이력 전체 초기화 (진행 중인 번호는 버리고 기존 추첨 시작 세션 유지)"""
    async with state.lock:
        await asyncio.to_thread(clear_records)
        was_started = state.is_started
        state.reset_state(keep_session=was_started)
        stats = state.get_stats()

    await manager.broadcast({
        "type": "DRAW_RESET",
        "data": stats
    })

    return {"success": True}


