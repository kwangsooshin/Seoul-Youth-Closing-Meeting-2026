import sqlite3
from pathlib import Path
from typing import List, Dict, Any, Optional

BASE_DIR = Path(__file__).resolve().parent.parent
SQLITE_PATH = BASE_DIR / "lottery.db"
SQL_DIR = Path(__file__).resolve().parent / "sql" / "sqlite"

# SQL 파일 로드
def _load_sql(filename: str) -> str:
    path = SQL_DIR / filename
    return path.read_text(encoding="utf-8")

SCHEMA_SQL = _load_sql("schema.sql")
HISTORY_SELECT_SQL = _load_sql("history_select.sql").strip()

PRIZE_FIELDS = ("id", "rank", "name", "count", "sort_order")

def sqlite_connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(SQLITE_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def init_sqlite(default_prizes: List[Dict[str, Any]]):
    """SQLite 테이블 초기화 및 기본 prizes 시드"""
    try:
        with sqlite_connect() as conn:
            conn.executescript(SCHEMA_SQL)
            # prizes 테이블이 비어있으면 초기 시드
            cur = conn.execute("SELECT COUNT(*) FROM prizes")
            if cur.fetchone()[0] == 0:
                for idx, p in enumerate(default_prizes):
                    conn.execute(
                        "INSERT INTO prizes (rank, name, count, sort_order) VALUES (?, ?, ?, ?)",
                        (p["rank"], p.get("name", ""), p["count"], idx),
                    )
            conn.commit()
    except Exception as e:
        print(f"[WARN] SQLite 초기화 오류: {e}")

def _normalize_prize(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": row["id"],
        "rank": row["rank"],
        "name": row.get("name") or "",
        "count": int(row["count"]),
        "sort_order": int(row.get("sort_order") or 0),
    }

def load_prizes() -> List[Dict[str, Any]]:
    with sqlite_connect() as conn:
        fields = ", ".join(PRIZE_FIELDS)
        rows = conn.execute(f"SELECT {fields} FROM prizes ORDER BY sort_order ASC, id ASC").fetchall()
        return [_normalize_prize(dict(r)) for r in rows]

def load_history() -> List[Dict[str, Any]]:
    with sqlite_connect() as conn:
        rows = conn.execute(f"{HISTORY_SELECT_SQL} ORDER BY h.id ASC").fetchall()
        return [dict(r) for r in rows]

def save_prizes(prizes: List[Dict[str, Any]], current_prizes: List[Dict[str, Any]]):
    existing_ids = {p["id"] for p in current_prizes}
    incoming_ids = {p["id"] for p in prizes if p.get("id") is not None}
    delete_ids = list(existing_ids - incoming_ids)

    with sqlite_connect() as conn:
        if delete_ids:
            conn.executemany("DELETE FROM prizes WHERE id = ?", [(i,) for i in delete_ids])
        for order, p in enumerate(prizes):
            if p.get("id") is not None and p["id"] in existing_ids:
                conn.execute(
                    "UPDATE prizes SET rank = ?, name = ?, count = ?, sort_order = ? WHERE id = ?",
                    (p["rank"], p.get("name", ""), p["count"], order, p["id"]),
                )
            else:
                conn.execute(
                    "INSERT INTO prizes (rank, name, count, sort_order) VALUES (?, ?, ?, ?)",
                    (p["rank"], p.get("name", ""), p["count"], order),
                )
        conn.commit()

def ensure_prize_exists(conn: sqlite3.Connection, prize_id: int, current_prizes: List[Dict[str, Any]]):
    """Supabase -> SQLite 중도 전환 시 FK 무결성을 위해 해당 등수를 SQLite에도 보장"""
    if conn.execute("SELECT 1 FROM prizes WHERE id = ?", (prize_id,)).fetchone():
        return
    prize = next((p for p in current_prizes if p["id"] == prize_id), None)
    if prize:
        conn.execute(
            "INSERT INTO prizes (id, rank, name, count, sort_order) VALUES (?, ?, ?, ?, ?)",
            (prize["id"], prize["rank"], prize["name"], prize["count"], prize["sort_order"]),
        )

def save_record(record: dict, current_prizes: List[Dict[str, Any]]) -> dict:
    with sqlite_connect() as conn:
        ensure_prize_exists(conn, record["prize_id"], current_prizes)
        cur = conn.execute(
            "INSERT INTO draw_history (prize_id, drawn_number, status) VALUES (?, ?, ?)",
            (record["prize_id"], record["drawn_number"], record["status"]),
        )
        conn.commit()
        row = conn.execute(f"{HISTORY_SELECT_SQL} WHERE h.id = ?", (cur.lastrowid,)).fetchone()
        return dict(row)

def clear_records():
    with sqlite_connect() as conn:
        conn.execute("DELETE FROM draw_history")
        conn.commit()
        print("[SUCCESS] 로컬 SQLite(lottery.db) 데이터가 초기화되었습니다.")
