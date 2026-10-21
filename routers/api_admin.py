import asyncio
import html
import hmac
import re
import time
from collections import defaultdict
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from core.config import ADMIN_PASSWORD, DEFAULT_BGM_URL, sanitize_youtube_url
from core.state import state
from core.websocket import manager
from core.net import get_rate_limit_keys
from core.auth import (
    create_admin_token,
    require_admin,
    revoke_admin_token,
    get_admin_token_from_request,
    set_admin_cookie,
    clear_admin_cookie,
)
from db import (
    save_prizes,
    save_app_config,
    load_access_logs,
    cleanup_old_access_logs,
    clear_all_access_logs,
)

router = APIRouter(prefix="/api", tags=["Admin"])

# 관리자 로그인 시도 무차별 대입(Brute-force) 방지 메모리 저장소
_failed_login_attempts: dict = defaultdict(list)
_global_failed_attempts: List[float] = []
MAX_LOGIN_ATTEMPTS = 5
MAX_GLOBAL_LOGIN_ATTEMPTS = 25
LOGIN_LOCKOUT_SECONDS = 60

_CONTROL_CHARS_RE = re.compile(r"[\x00-\x1f\x7f<>]")


def _sanitize_text(value: Optional[str], max_len: int) -> str:
    """제어문자 및 HTML 태그 괄호(<, >) 제거 및 중복 이스케이프 방지 정규화"""
    if not value:
        return ""
    unescaped = html.unescape(value).strip()
    cleaned = _CONTROL_CHARS_RE.sub("", unescaped)
    return cleaned[:max_len]


def _prune_failed_attempts(now: float):
    """오래된 로그인 실패 기록 전역 청소 (메모리 누수 및 DoS 방지)"""
    global _global_failed_attempts
    _global_failed_attempts = [t for t in _global_failed_attempts if now - t < LOGIN_LOCKOUT_SECONDS]
    stale_keys = [
        k for k, attempts in _failed_login_attempts.items()
        if not attempts or (now - attempts[-1] >= LOGIN_LOCKOUT_SECONDS)
    ]
    for k in stale_keys:
        _failed_login_attempts.pop(k, None)


def _check_login_rate_limit(rate_keys: List[str]):
    global _global_failed_attempts
    now = time.time()
    if len(_failed_login_attempts) > 50 or len(_global_failed_attempts) > MAX_GLOBAL_LOGIN_ATTEMPTS:
        _prune_failed_attempts(now)

    # 1. 전역 브루트포스 방어 (IP 스푸핑/분산 공격 시 전체 보호)
    _global_failed_attempts = [t for t in _global_failed_attempts if now - t < LOGIN_LOCKOUT_SECONDS]
    if len(_global_failed_attempts) >= MAX_GLOBAL_LOGIN_ATTEMPTS:
        retry_after = int(LOGIN_LOCKOUT_SECONDS - (now - _global_failed_attempts[0]))
        raise HTTPException(
            status_code=429,
            detail=f"비정상적인 로그인 시도가 감지되었습니다. {max(1, retry_after)}초 후 다시 시도해주세요."
        )

    # 2. 클라이언트 IP 및 소켓 IP별 제한 확인
    for key in rate_keys:
        attempts = [t for t in _failed_login_attempts.get(key, []) if now - t < LOGIN_LOCKOUT_SECONDS]
        if attempts:
            _failed_login_attempts[key] = attempts
        else:
            _failed_login_attempts.pop(key, None)

        if len(attempts) >= MAX_LOGIN_ATTEMPTS:
            retry_after = int(LOGIN_LOCKOUT_SECONDS - (now - attempts[0]))
            raise HTTPException(
                status_code=429,
                detail=f"비밀번호 입력 시도 횟수를 초과했습니다. {max(1, retry_after)}초 후 다시 시도해주세요."
            )


class VerifyPasswordRequest(BaseModel):
    password: str = Field(..., min_length=1, max_length=128)


@router.post("/admin/verify")
async def verify_admin(req: VerifyPasswordRequest, request: Request, response: Response):
    rate_keys = get_rate_limit_keys(request)
    _check_login_rate_limit(rate_keys)

    # 타이밍 공격 방지를 위한 hmac.compare_digest 사용
    if hmac.compare_digest(req.password, ADMIN_PASSWORD):
        for key in rate_keys:
            _failed_login_attempts.pop(key, None)
        token = create_admin_token()
        set_admin_cookie(request, response, token)
        return {"success": True, "token": token}

    now = time.time()
    _global_failed_attempts.append(now)
    for key in rate_keys:
        _failed_login_attempts[key].append(now)
    raise HTTPException(status_code=401, detail="비밀번호가 올바르지 않습니다.")


@router.post("/admin/logout")
async def logout_admin(request: Request, response: Response):
    """세션 토큰 폐기 (로그아웃)"""
    token = get_admin_token_from_request(request)
    if token:
        revoke_admin_token(token)
    cookie_token = request.cookies.get("admin_token")
    if cookie_token:
        revoke_admin_token(cookie_token)
    clear_admin_cookie(request, response)
    return {"success": True, "message": "성공적으로 로그아웃되었습니다."}


@router.post("/admin/ping", dependencies=[Depends(require_admin)])
async def ping_admin():
    """관리자 활동 유지를 위한 가벼운 핑 (유휴 세션 및 송출 타이머 갱신)"""
    return {
        "success": True,
        "session_last_active_at": state.session_last_active_at
    }


@router.get("/state")
async def get_state():
    return state.get_stats()


class PrizeInput(BaseModel):
    id: Optional[int] = None
    rank: str
    count: int
    name: Optional[str] = ""


class ConfigUpdateRequest(BaseModel):
    min_number: int
    max_number: int
    bgm_youtube_url: Optional[str] = DEFAULT_BGM_URL
    prizes: Optional[List[PrizeInput]] = None  # None이면 등수 설정은 변경하지 않음


def _are_prizes_equal(incoming: list, current: list) -> bool:
    """등수 목록의 실질적 변경 여부 확인 (변경 없을 시 DB I/O 생략)"""
    if len(incoming) != len(current):
        return False
    for order, (inc, cur) in enumerate(zip(incoming, current)):
        if (
            inc.get("id") is None
            or inc.get("id") != cur.get("id")
            or inc.get("rank") != cur.get("rank")
            or (inc.get("name") or "") != (cur.get("name") or "")
            or int(inc.get("count", 0)) != int(cur.get("count", 0))
            or int(cur.get("sort_order", order)) != order
        ):
            return False
    return True


def _sync_history_prize_labels():
    """인메모리 추첨 이력 및 진행 중 항목에 변경된 등수명/상품명을 즉시 반영 (불필요한 DB 재조회 제거)"""
    prize_map = {p["id"]: p for p in state.prizes if p.get("id") is not None}
    for h in state.history:
        matched = prize_map.get(h.get("prize_id"))
        if matched:
            h["prize_rank"] = matched["rank"]
            h["prize_name"] = matched.get("name", "")
    if state.pending_draw:
        matched_pending = prize_map.get(state.pending_draw.get("prize_id"))
        if matched_pending:
            state.pending_draw["prize_rank"] = matched_pending["rank"]
            state.pending_draw["prize_name"] = matched_pending.get("name", "")


@router.post("/config", dependencies=[Depends(require_admin)])
async def update_config(req: ConfigUpdateRequest):
    if req.min_number < 1:
        raise HTTPException(status_code=400, detail="최소 번호는 1 이상이어야 합니다.")
    if req.max_number > 1000:
        raise HTTPException(status_code=400, detail="최대 번호는 1,000 이하이어야 합니다.")
    if req.min_number >= req.max_number:
        raise HTTPException(status_code=400, detail="최소 번호는 최대 번호보다 작아야 합니다.")

    try:
        clean_bgm_url = sanitize_youtube_url(req.bgm_youtube_url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    async with state.lock:
        prizes_to_save = None

        # 등수(prizes) 변경 검증
        if req.prizes is not None:
            if len(req.prizes) > 100:
                raise HTTPException(status_code=400, detail="등수는 최대 100개까지만 설정할 수 있습니다.")

            valid_existing_ids = {p["id"] for p in state.prizes if p.get("id") is not None}
            seen_ids = set()
            prizes = []
            for p in req.prizes:
                rank = _sanitize_text(p.rank, 50)
                if not rank or p.count <= 0:
                    continue
                # 현재 상태에 존재하는 유효 ID만 인정 (임의/조작된 ID 주입 방지)
                pid = p.id if (p.id is not None and p.id in valid_existing_ids) else None
                if pid is not None:
                    if pid in seen_ids:
                        raise HTTPException(status_code=400, detail="중복된 등수 ID가 포함되어 있습니다.")
                    seen_ids.add(pid)
                prizes.append({
                    "id": pid,
                    "rank": rank,
                    "count": max(1, min(1000, p.count)),
                    "name": _sanitize_text(p.name, 100),
                })

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

            if not _are_prizes_equal(prizes, state.prizes):
                prizes_to_save = prizes

        new_config = {
            "min_number": req.min_number,
            "max_number": req.max_number,
            "bgm_youtube_url": clean_bgm_url,
        }
        config_changed = new_config != state.config

        # 변경된 항목만 DB 반영 (불필요한 재조회 제거, 동시 변경 시 병렬 저장)
        if prizes_to_save is not None and config_changed:
            try:
                saved_prizes, _ = await asyncio.gather(
                    asyncio.to_thread(save_prizes, prizes_to_save, state.prizes),
                    asyncio.to_thread(save_app_config, dict(new_config)),
                )
                state.prizes = saved_prizes
                _sync_history_prize_labels()
                state.refresh_selected_prize()
            except Exception as e:
                print(f"[ERROR] 등수 및 설정 저장 실패: {e}")
                raise HTTPException(status_code=500, detail="등수 설정을 저장하는 중 서버 오류가 발생했습니다.")
        elif prizes_to_save is not None:
            try:
                state.prizes = await asyncio.to_thread(save_prizes, prizes_to_save, state.prizes)
                _sync_history_prize_labels()
                state.refresh_selected_prize()
            except Exception as e:
                print(f"[ERROR] 등수 저장 실패: {e}")
                raise HTTPException(status_code=500, detail="등수 설정을 저장하는 중 서버 오류가 발생했습니다.")
        elif config_changed:
            try:
                await asyncio.to_thread(save_app_config, dict(new_config))
            except Exception as e:
                print(f"[WARN] 설정 DB 저장 오류: {e}")

        state.config = new_config
        stats = state.get_stats()

    await manager.broadcast({"type": "CONFIG_UPDATED", "data": stats})
    return {"success": True, "config": stats["config"], "data": stats}


VALID_BGM_ACTIONS = {
    "play", "pause", "stop",
    "mute", "unmute",
    "master_mute", "master_unmute",
    "bgm_play", "bgm_pause", "bgm_stop",
    "sfx_mute", "sfx_unmute",
    "set_volume"
}


class BgmControlRequest(BaseModel):
    action: str  # "play", "pause", "mute", "unmute", "set_volume" 등
    volume: Optional[int] = 30


@router.post("/bgm/control", dependencies=[Depends(require_admin)])
async def control_bgm(req: BgmControlRequest):
    if req.action not in VALID_BGM_ACTIONS:
        raise HTTPException(status_code=400, detail="유효하지 않은 오디오 제어 액션입니다.")

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


@router.get("/admin/audit-logs", dependencies=[Depends(require_admin)])
async def get_audit_logs(limit: int = 100):
    """페이지 접속 감사 로그(Audit Log) 목록 조회 (관리자 인증)"""
    effective_limit = 1000 if (limit <= 0 or limit > 1000) else limit
    logs = await asyncio.to_thread(load_access_logs, effective_limit)
    return {"success": True, "logs": logs}


@router.post("/admin/audit-logs/cleanup", dependencies=[Depends(require_admin)])
async def cleanup_audit_logs_manual(hours: int = 24):
    """지정된 시간(기본 24시간) 이전의 감사 로그 수동 정리 (hours=0 시 전체 정리)"""
    if hours < 0 or hours > 8760:
        raise HTTPException(status_code=400, detail="유효한 시간(0 ~ 8760시간)을 입력해주세요.")

    if hours == 0:
        deleted_count = await asyncio.to_thread(clear_all_access_logs)
        return {"success": True, "message": f"전체 감사 로그 {deleted_count}건을 초기화했습니다."}

    await asyncio.to_thread(cleanup_old_access_logs, hours)
    return {"success": True, "message": f"{hours}시간 경과 감사 로그를 정리했습니다."}


@router.post("/admin/audit-logs/clear-all", dependencies=[Depends(require_admin)])
async def clear_all_audit_logs_endpoint():
    """모든 접속 감사 로그 전체 초기화/삭제"""
    deleted_count = await asyncio.to_thread(clear_all_access_logs)
    return {"success": True, "message": f"전체 접속 감사 로그 {deleted_count}건을 모두 초기화했습니다."}

