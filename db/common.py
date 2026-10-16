from typing import List, Dict, Any, Tuple, Set

PRIZE_FIELDS = ("id", "rank", "name", "count", "sort_order")


def normalize_prize(row: Dict[str, Any]) -> Dict[str, Any]:
    """DB 조회 결과(Row)를 표준 등수(Prize) 딕셔너리 포맷으로 정규화"""
    return {
        "id": row["id"],
        "rank": row["rank"],
        "name": row.get("name") or "",
        "count": int(row["count"]),
        "sort_order": int(row.get("sort_order") or 0),
    }


def compute_prize_diff(
    prizes: List[Dict[str, Any]],
    current_prizes: List[Dict[str, Any]],
) -> Tuple[Set[int], List[int]]:
    """현재 등수 목록과 신규 등수 목록을 비교하여 유지 대상 ID 집합과 삭제 대상 ID 리스트 반환"""
    existing_ids = {p["id"] for p in current_prizes if p.get("id") is not None}
    incoming_ids = {p["id"] for p in prizes if p.get("id") is not None}
    delete_ids = list(existing_ids - incoming_ids)
    return existing_ids, delete_ids
