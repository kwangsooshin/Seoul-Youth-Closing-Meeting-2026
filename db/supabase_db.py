from typing import List, Dict, Any, Optional

PRIZE_FIELDS = ("id", "rank", "name", "count", "sort_order")
SUPABASE_HISTORY_SELECT = "id, prize_id, drawn_number, status, created_at, prizes(rank, name)"

def _normalize_prize(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": row["id"],
        "rank": row["rank"],
        "name": row.get("name") or "",
        "count": int(row["count"]),
        "sort_order": int(row.get("sort_order") or 0),
    }

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
    res = client.table("prizes").select("id").limit(1).execute()
    if not res.data:
        client.table("prizes").insert(
            [{**p, "sort_order": idx} for idx, p in enumerate(default_prizes)]
        ).execute()
        print("[INFO] Supabase 'prizes' 테이블에 기본 등수를 시드했습니다.")

def seed_config_if_empty(client, default_config: Dict[str, Any]):
    res = client.table("app_config").select("id").limit(1).execute()
    if not res.data:
        client.table("app_config").insert({
            "id": "current",
            "data": default_config
        }).execute()
        print("[INFO] Supabase 'app_config' 테이블에 기본 설정을 시드했습니다.")

def load_config_db(client) -> Optional[Dict[str, Any]]:
    res = client.table("app_config").select("data").eq("id", "current").limit(1).execute()
    if res.data and len(res.data) > 0:
        return res.data[0]["data"]
    return None

def save_config_db(client, config: Dict[str, Any]):
    client.table("app_config").upsert({
        "id": "current",
        "data": config
    }).execute()

def load_prizes(client) -> List[Dict[str, Any]]:
    res = client.table("prizes").select(",".join(PRIZE_FIELDS)).order("sort_order").order("id").execute()
    return [_normalize_prize(r) for r in (res.data or [])]

def load_history(client) -> List[Dict[str, Any]]:
    res = client.table("draw_history").select(SUPABASE_HISTORY_SELECT).order("id", desc=False).execute()
    return [_flatten_history(r) for r in (res.data or [])]

def save_prizes(client, prizes: List[Dict[str, Any]], current_prizes: List[Dict[str, Any]]):
    existing_ids = {p["id"] for p in current_prizes}
    incoming_ids = {p["id"] for p in prizes if p.get("id") is not None}
    delete_ids = list(existing_ids - incoming_ids)

    if delete_ids:
        client.table("prizes").delete().in_("id", delete_ids).execute()

    for order, p in enumerate(prizes):
        payload = {"rank": p["rank"], "name": p.get("name", ""), "count": p["count"], "sort_order": order}
        if p.get("id") is not None and p["id"] in existing_ids:
            client.table("prizes").update(payload).eq("id", p["id"]).execute()
        else:
            client.table("prizes").insert(payload).execute()

def save_record(client, record: dict) -> Optional[dict]:
    res = client.table("draw_history").insert(record).execute()
    if res.data:
        new_id = res.data[0]["id"]
        joined = client.table("draw_history").select(SUPABASE_HISTORY_SELECT).eq("id", new_id).execute()
        if joined.data:
            return _flatten_history(joined.data[0])
    return None

def delete_last_record(client) -> Optional[int]:
    res = client.table("draw_history").select("id").order("id", desc=True).limit(1).execute()
    if res.data:
        last_id = res.data[0]["id"]
        client.table("draw_history").delete().eq("id", last_id).execute()
        return last_id
    return None

def clear_records(client):
    client.table("draw_history").delete().neq("id", 0).execute()

def save_access_log(client, ip: str, page_type: str, path: str, user_agent: str = ""):
    """Supabase access_logs 테이블에 접속 감사 로그 저장"""
    client.table("access_logs").insert({
        "ip": ip,
        "page_type": page_type,
        "path": path,
        "user_agent": user_agent,
    }).execute()

def load_access_logs(client, limit: int = 100) -> List[Dict[str, Any]]:
    """Supabase access_logs 테이블에서 접속 감사 로그 최신순 조회"""
    res = client.table("access_logs").select("id, ip, page_type, path, user_agent, created_at").order("id", desc=True).limit(limit).execute()
    return res.data or []

