from typing import Optional, List
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from core.config import ADMIN_PASSWORD, DEFAULT_BGM_URL
from core.state import state
from core.websocket import manager
from db import save_prizes, load_prizes, load_history, save_app_config, load_access_logs

router = APIRouter(prefix="/api", tags=["Admin"])



class VerifyPasswordRequest(BaseModel):
    password: str


@router.post("/admin/verify")
async def verify_admin(req: VerifyPasswordRequest):
    if req.password == ADMIN_PASSWORD:
        return {"success": True}
    raise HTTPException(status_code=401, detail="비밀번호가 올바르지 않습니다.")


@router.get("/state")
async def get_state():
    return state.get_stats()


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


@router.post("/config")
async def update_config(req: ConfigUpdateRequest):
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
        in_use_ids = {h["prize_id"] for h in state.history}
        if state.pending_draw:
            in_use_ids.add(state.pending_draw["prize_id"])
        blocked = [p["rank"] for p in state.prizes if p["id"] in in_use_ids and p["id"] not in incoming_ids]
        if blocked:
            raise HTTPException(
                status_code=400,
                detail=f"추첨 이력이 있는 등수는 삭제할 수 없습니다: {', '.join(blocked)} (이력 초기화 후 삭제하세요)",
            )

        try:
            save_prizes(prizes, state.prizes)
            state.prizes = load_prizes()
            state.history = load_history()  # 등수명 변경을 이력(JOIN)에 반영
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"등수 저장 실패: {e}")

    # 번호 범위 / BGM 설정 DB(Supabase / SQLite)에 영구 저장
    new_config = {
        "min_number": req.min_number,
        "max_number": req.max_number,
        "bgm_youtube_url": req.bgm_youtube_url or DEFAULT_BGM_URL,
    }
    try:
        save_app_config(new_config)
    except Exception as e:
        print(f"[WARN] 설정 DB 저장 오류: {e}")

    state.config = new_config

    # 상태 브로드캐스트
    stats = state.get_stats()
    await manager.broadcast({"type": "CONFIG_UPDATED", "data": stats})
    return {"success": True, "config": stats["config"]}


class BgmControlRequest(BaseModel):
    password: str
    action: str  # "play", "pause", "mute", "unmute", "set_volume"
    volume: Optional[int] = 30


@router.post("/bgm/control")
async def control_bgm(req: BgmControlRequest):
    if req.password != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="인증 실패")

    await manager.broadcast({
        "type": "BGM_CONTROL",
        "action": req.action,
        "volume": req.volume
    })
    return {"success": True, "action": req.action, "volume": req.volume}


@router.get("/admin/audit-logs")
async def get_audit_logs(password: str, limit: int = 50):
    """페이지 접속 감사 로그(Audit Log) 목록 조회 (관리자 인증 필요)"""
    if password != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="인증 실패")

    logs = load_access_logs(limit=min(limit, 200))
    return {"success": True, "logs": logs}

