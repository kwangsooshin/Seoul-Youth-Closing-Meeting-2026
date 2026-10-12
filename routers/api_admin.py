from typing import Optional, List
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from core.config import ADMIN_PASSWORD, DEFAULT_BGM_URL
from core.state import state
from core.websocket import manager
from core.auth import create_admin_token, is_authenticated_admin
from db import save_prizes, load_prizes, load_history, save_app_config, load_access_logs, cleanup_old_access_logs, clear_all_access_logs

router = APIRouter(prefix="/api", tags=["Admin"])


class VerifyPasswordRequest(BaseModel):
    password: str


@router.post("/admin/verify")
async def verify_admin(req: VerifyPasswordRequest):
    if req.password == ADMIN_PASSWORD:
        token = create_admin_token()
        return {"success": True, "token": token}
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
    password: Optional[str] = ""
    min_number: int
    max_number: int
    bgm_youtube_url: Optional[str] = DEFAULT_BGM_URL
    prizes: Optional[List[PrizeInput]] = None  # None이면 등수 설정은 변경하지 않음


@router.post("/config")
async def update_config(req: ConfigUpdateRequest, request: Request):
    if not is_authenticated_admin(request, legacy_password=req.password):
        raise HTTPException(status_code=401, detail="인증 실패 (세션 토큰 또는 비밀번호가 필요합니다)")


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
    password: Optional[str] = ""
    action: str  # "play", "pause", "mute", "unmute", "set_volume"
    volume: Optional[int] = 30


@router.post("/bgm/control")
async def control_bgm(req: BgmControlRequest, request: Request):
    if not is_authenticated_admin(request, legacy_password=req.password):
        raise HTTPException(status_code=401, detail="인증 실패 (세션 토큰 또는 비밀번호가 필요합니다)")


    # 오디오 제어 액션별 상태 반영
    if req.action in ("master_mute", "mute"):
        state.audio_state["master_muted"] = True
    elif req.action in ("master_unmute", "unmute"):
        state.audio_state["master_muted"] = False
    elif req.action in ("bgm_play", "play"):
        state.audio_state["bgm_paused"] = False
    elif req.action in ("bgm_pause", "pause", "bgm_stop", "stop"):
        state.audio_state["bgm_paused"] = True
    elif req.action == "sfx_mute":
        state.audio_state["sfx_muted"] = True
    elif req.action == "sfx_unmute":
        state.audio_state["sfx_muted"] = False
    elif req.action == "set_volume":
        if req.volume is not None:
            state.audio_state["volume"] = max(0, min(100, int(req.volume)))

    current_volume = req.volume if req.volume is not None else state.audio_state.get("volume", 30)

    await manager.broadcast({
        "type": "BGM_CONTROL",
        "action": req.action,
        "volume": current_volume,
        "audio_state": state.audio_state
    })
    return {
        "success": True,
        "action": req.action,
        "volume": current_volume,
        "audio_state": state.audio_state
    }


@router.get("/admin/audit-logs")
async def get_audit_logs(request: Request, limit: int = 100, password: Optional[str] = None):
    """페이지 접속 감사 로그(Audit Log) 목록 조회 (Bearer 세션 토큰 또는 비밀번호 인증)"""
    if not is_authenticated_admin(request, legacy_password=password):
        raise HTTPException(status_code=401, detail="인증 실패 (유효한 관리자 세션 토큰이 필요합니다)")

    # limit이 0 이하이거나 미지정 시 최대 1000건(최근 24시간 전체 보관분 수용) 조회
    effective_limit = 1000 if (limit <= 0 or limit > 1000) else limit
    logs = load_access_logs(limit=effective_limit)
    return {"success": True, "logs": logs}


@router.post("/admin/audit-logs/cleanup")
async def cleanup_audit_logs_manual(request: Request, hours: int = 24, password: Optional[str] = None):
    """지정된 시간(기본 24시간) 이전의 감사 로그 수동 정리 (hours=0 시 전체 정리)"""
    if not is_authenticated_admin(request, legacy_password=password):
        raise HTTPException(status_code=401, detail="인증 실패")

    if hours <= 0:
        deleted_count = clear_all_access_logs()
        return {"success": True, "message": f"전체 감사 로그 {deleted_count}건을 초기화했습니다."}

    cleanup_old_access_logs(hours=hours)
    return {"success": True, "message": f"{hours}시간 경과 감사 로그를 정리했습니다."}


@router.post("/admin/audit-logs/clear-all")
async def clear_all_audit_logs_endpoint(request: Request, password: Optional[str] = None):
    """모든 접속 감사 로그 전체 초기화/삭제"""
    if not is_authenticated_admin(request, legacy_password=password):
        raise HTTPException(status_code=401, detail="인증 실패")

    deleted_count = clear_all_access_logs()
    return {"success": True, "message": f"전체 접속 감사 로그 {deleted_count}건을 모두 초기화했습니다."}


