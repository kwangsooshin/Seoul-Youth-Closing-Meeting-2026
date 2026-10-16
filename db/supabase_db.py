from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta, timezone
from core.config import SCHEMA_NAME
from .common import PRIZE_FIELDS, normalize_prize, compute_prize_diff

SUPABASE_HISTORY_SELECT = "id, prize_id, drawn_number, status, created_at, prizes(rank, name)"

def get_schema() -> str:
    """실행 환경 ZONE(dev/service)에 따른 Supabase 스키마명 반환"""
    return SCHEMA_NAME

def table(client, table_name: str):
    """현재 스키마(dev 또는 service)의 테이블 쿼리 빌더 반환"""
    return client.schema(get_schema()).table(table_name)

def _flatten_history(row: Dict[str, Any]) -> Dict[str, Any]:
    prize = row.get("prizes") or {}
    return {
        "id": row["id"],
        "prize_id": row["prize_id"],
        "prize_rank": prize.get("rank", ""),
        "prize_name": prize.get("name") or "",
        "drawn_number": row["drawn_number"],
        "status": row["status"],
        "created_at": row.get("created_at"),
    }

def seed_prizes_if_empty(client, default_prizes: List[Dict[str, Any]]):
    schema = get_schema()
    res = table(client, "prizes").select("id").limit(1).execute()
    if not res.data:
        table(client, "prizes").insert(
            [{**p, "sort_order": idx} for idx, p in enumerate(default_prizes)]
        ).execute()
        print(f"[INFO] Supabase '{schema}.prizes' 테이블에 기본 등수를 시드했습니다.")

def seed_config_if_empty(client, default_config: Dict[str, Any]):
    schema = get_schema()
    res = table(client, "app_config").select("id").limit(1).execute()
    if not res.data:
        table(client, "app_config").insert({
            "id": "current",
            "data": default_config
        }).execute()
        print(f"[INFO] Supabase '{schema}.app_config' 테이블에 기본 설정을 시드했습니다.")

def load_config_db(client) -> Optional[Dict[str, Any]]:
    res = table(client, "app_config").select("data").eq("id", "current").limit(1).execute()
    if res.data and len(res.data) > 0:
        return res.data[0]["data"]
    return None

def save_config_db(client, config: Dict[str, Any]):
    table(client, "app_config").upsert({
        "id": "current",
        "data": config
    }).execute()

def load_prizes(client) -> List[Dict[str, Any]]:
    res = table(client, "prizes").select(",".join(PRIZE_FIELDS)).order("sort_order").order("id").execute()
    return [normalize_prize(r) for r in (res.data or [])]

def load_history(client) -> List[Dict[str, Any]]:
    res = table(client, "draw_history").select(SUPABASE_HISTORY_SELECT).order("id", desc=False).execute()
    return [_flatten_history(r) for r in (res.data or [])]

def save_prizes(client, prizes: List[Dict[str, Any]], current_prizes: List[Dict[str, Any]]):
    existing_ids, delete_ids = compute_prize_diff(prizes, current_prizes)

    if delete_ids:
        table(client, "prizes").delete().in_("id", delete_ids).execute()

    for order, p in enumerate(prizes):
        payload = {"rank": p["rank"], "name": p.get("name", ""), "count": p["count"], "sort_order": order}
        if p.get("id") is not None and p["id"] in existing_ids:
            table(client, "prizes").update(payload).eq("id", p["id"]).execute()
        else:
            table(client, "prizes").insert(payload).execute()


def save_record(client, record: dict) -> Optional[dict]:
    res = table(client, "draw_history").insert(record).execute()
    if res.data:
        new_id = res.data[0]["id"]
        joined = table(client, "draw_history").select(SUPABASE_HISTORY_SELECT).eq("id", new_id).execute()
        if joined.data:
            return _flatten_history(joined.data[0])
    return None

def delete_last_record(client) -> Optional[int]:
    res = table(client, "draw_history").select("id").order("id", desc=True).limit(1).execute()
    if res.data:
        last_id = res.data[0]["id"]
        table(client, "draw_history").delete().eq("id", last_id).execute()
        return last_id
    return None

def clear_records(client):
    table(client, "draw_history").delete().neq("id", 0).execute()

def save_access_log(client, ip: str, page_type: str, path: str, user_agent: str = ""):
    """Supabase access_logs 테이블에 접속 감사 로그 저장"""
    table(client, "access_logs").insert({
        "ip": ip,
        "page_type": page_type,
        "path": path,
        "user_agent": user_agent,
    }).execute()

def load_access_logs(client, limit: int = 100) -> List[Dict[str, Any]]:
    """Supabase access_logs 테이블에서 접속 감사 로그 최신순 조회"""
    res = table(client, "access_logs").select("id, ip, page_type, path, user_agent, created_at").order("id", desc=True).limit(limit).execute()
    return res.data or []

def cleanup_old_access_logs(client, hours: int = 24) -> int:
    """Supabase access_logs 테이블에서 지정 시간(기본 24시간) 이전 로그 자동 삭제"""
    try:
        schema = get_schema()
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        res = table(client, "access_logs").delete().lt("created_at", cutoff).execute()
        deleted_count = len(res.data) if res.data else 0
        if deleted_count > 0:
            print(f"[INFO] Supabase [{schema}]: {deleted_count}건의 {hours}시간 경과 감사 로그를 정리했습니다.")
        return deleted_count
    except Exception as e:
        print(f"[WARN] Supabase 감사 로그 정리 오류: {e}")
        return 0

def clear_all_access_logs(client) -> int:
    """Supabase access_logs 테이블 전체 초기화/삭제"""
    try:
        schema = get_schema()
        res = table(client, "access_logs").delete().neq("id", 0).execute()
        deleted_count = len(res.data) if res.data else 0
        print(f"[INFO] Supabase [{schema}]: 전체 {deleted_count}건의 감사 로그를 초기화했습니다.")
        return deleted_count
    except Exception as e:
        print(f"[WARN] Supabase 감사 로그 전체 삭제 오류: {e}")
        return 0
