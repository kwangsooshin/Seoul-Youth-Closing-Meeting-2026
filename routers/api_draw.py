import asyncio
import secrets
import time
from typing import Optional
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from core.state import state, SESSION_TIMEOUT_SECONDS
from core.websocket import manager
from core.auth import is_authenticated_admin
from db import save_record, delete_last_record, clear_records

router = APIRouter(prefix="/api/draw", tags=["Draw"])

# 세션 자동 종료(3시간) 비동기 타이머 태스크 핸들러
_session_timeout_task: Optional[asyncio.Task] = None


async def _auto_close_session_timer():
    """대기화면 해제 후 관리자 세션 무갱신 상태로 3시간이 경과하면 자동으로 대기화면으로 복귀하고 BGM을 종료합니다."""
    try:
        while state.is_started:
            now = time.time()
            last_active = state.session_last_active_at or state.session_started_at or now
            remaining = SESSION_TIMEOUT_SECONDS - (now - last_active)
            if remaining <= 0:
                print("[SESSION_TIMEOUT] 관리자 세션 갱신 없이 3시간 경과: 송출 스크린을 대기화면으로 자동 복귀시키고 BGM을 종료합니다.")
                state.stop_session()
                # BGM 종료 (정지 상태로 전환)
                state.audio_state["bgm_paused"] = True

                stats = state.get_stats()
                # 1. 대기화면 전환 브로드캐스트 (auto_timeout=True 플래그)
                await manager.broadcast({
                    "type": "LOTTERY_SESSION_STATE",
                    "started": False,
                    "auto_timeout": True,
                    "data": stats
                })
                # 2. BGM 정지 브로드캐스트
                await manager.broadcast({
                    "type": "BGM_CONTROL",
                    "action": "stop",
                    "audio_state": state.audio_state
                })
                break

            # 남은 시간(최대 30초 주기)만큼 대기 후 재검사
            await asyncio.sleep(min(max(1, remaining), 30))
    except asyncio.CancelledError:
        pass
    except Exception as e:
        print(f"[WARN] 세션 3시간 자동 종료 태스크 오류: {e}")


class LotterySessionRequest(BaseModel):
    started: bool


@router.post("/session")
async def set_lottery_session(req: LotterySessionRequest, request: Request):
    """현장 추첨 이벤트 시작 및 대기 모드 전환 (관리자 무조작 3시간 후 자동 복귀 타이머 가동)"""
    global _session_timeout_task
    if not is_authenticated_admin(request):
        raise HTTPException(status_code=401, detail="인증 실패 (유효한 관리자 세션 토큰이 필요합니다)")

    if req.started:
        # 기존 타이머 취소 후 관리자 활동 기준 3시간 슬라이딩 타이머 시작
        if _session_timeout_task and not _session_timeout_task.done():
            _session_timeout_task.cancel()
        state.start_session()
        _session_timeout_task = asyncio.create_task(_auto_close_session_timer())
        print(f"[SESSION] 추첨 세션 시작: 대기화면 해제 (관리자 무조작 3시간 자동 종료 타이머 가동, 시작시각: {state.session_started_at})")
    else:
        # 수동으로 대기 모드 전환 시 타이머 취소
        if _session_timeout_task and not _session_timeout_task.done():
            _session_timeout_task.cancel()
        state.stop_session()
        print("[SESSION] 추첨 세션 중지: 대기화면 표시 전환")

    stats = state.get_stats()
    await manager.broadcast({
        "type": "LOTTERY_SESSION_STATE",
        "started": state.is_started,
        "auto_timeout": False,
        "data": stats
    })
    return {
        "success": True,
        "started": state.is_started,
        "session_started_at": state.session_started_at,
        "session_last_active_at": state.session_last_active_at
    }


class DrawStartRequest(BaseModel):
    prize_id: int


class PrizeSelectRequest(BaseModel):
    prize_id: int


@router.post("/select-prize")
async def select_prize(req: PrizeSelectRequest, request: Request):
    """관리자 콘솔에서 추첨할 등수 선택 변경 시 디스플레이와 실시간 동기화"""
    if not is_authenticated_admin(request):
        raise HTTPException(status_code=401, detail="인증 실패 (유효한 관리자 세션 토큰이 필요합니다)")

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
async def start_draw(req: DrawStartRequest, request: Request):
    if not is_authenticated_admin(request):
        raise HTTPException(status_code=401, detail="인증 실패 (유효한 관리자 세션 토큰이 필요합니다)")

    if not state.is_started:
        raise HTTPException(status_code=400, detail="현재 대기화면 상태입니다. 먼저 '대기화면 해제'를 해주세요.")

    if state.pending_draw is not None:
        return {"success": False, "message": "이미 진행 중인 추첨 번호가 있습니다. 확정 또는 패스를 먼저 처리하세요.", "current": state.pending_draw}

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
        "status": "DRAWING"
    }

    # 브로드캐스트: 추첨 롤링 시작 이벤트
    await manager.broadcast({
        "type": "DRAW_ROLLING_START",
        "data": state.pending_draw
    })

    return {"success": True, "picked_number": picked_number, "data": state.pending_draw}


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
async def confirm_draw(request: Request):
    """현재 번호 당첨 확정"""
    if not is_authenticated_admin(request):
        raise HTTPException(status_code=401, detail="인증 실패 (유효한 관리자 세션 토큰이 필요합니다)")

    if not state.pending_draw:
        raise HTTPException(status_code=400, detail="확정할 추첨 번호가 없습니다.")

    return await _finalize_pending_draw("CONFIRMED", "DRAW_CONFIRMED")


@router.post("/pass")
async def pass_draw(request: Request):
    """호명 시 부재자 패스 처리 (넘어가기)"""
    if not is_authenticated_admin(request):
        raise HTTPException(status_code=401, detail="인증 실패 (유효한 관리자 세션 토큰이 필요합니다)")

    if not state.pending_draw:
        raise HTTPException(status_code=400, detail="패스할 추첨 번호가 없습니다.")

    return await _finalize_pending_draw("PASSED", "DRAW_PASSED")


@router.post("/cancel-last")
async def cancel_last_draw(request: Request):
    """방금 확정/패스된 가장 최근 추첨 건 취소 및 롤백"""
    if not is_authenticated_admin(request):
        raise HTTPException(status_code=401, detail="인증 실패 (유효한 관리자 세션 토큰이 필요합니다)")

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


@router.post("/reset")
async def reset_draw(request: Request):
    """추첨 이력 전체 초기화"""
    if not is_authenticated_admin(request):
        raise HTTPException(status_code=401, detail="인증 실패 (유효한 관리자 세션 토큰이 필요합니다)")

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

