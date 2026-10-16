import json
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

from .common import PRIZE_FIELDS, normalize_prize, compute_prize_diff

def sqlite_connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(SQLITE_PATH), timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn

def init_sqlite(default_prizes: List[Dict[str, Any]], default_config: Optional[Dict[str, Any]] = None):
    """SQLite 테이블 초기화 및 기본 prizes/config 시드"""
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
            # app_config 테이블이 비어있으면 초기 config 시드
            if default_config:
                cur_cfg = conn.execute("SELECT COUNT(*) FROM app_config WHERE id = 'current'")
                if cur_cfg.fetchone()[0] == 0:
                    conn.execute(
                        "INSERT INTO app_config (id, data) VALUES ('current', ?)",
                        (json.dumps(default_config, ensure_ascii=False),),
                    )
            conn.commit()
    except Exception as e:
        print(f"[WARN] SQLite 초기화 오류: {e}")

def load_config_db() -> Optional[Dict[str, Any]]:
    """SQLite에서 app_config JSON 로드"""
    try:
        with sqlite_connect() as conn:
            row = conn.execute("SELECT data FROM app_config WHERE id = 'current'").fetchone()
            if row and row["data"]:
                return json.loads(row["data"])
    except Exception as e:
        print(f"[WARN] SQLite config 조회 오류: {e}")
    return None

def save_config_db(config: Dict[str, Any]):
    """SQLite에 app_config JSON 저장"""
    with sqlite_connect() as conn:
        conn.execute(
            "INSERT INTO app_config (id, data, updated_at) VALUES ('current', ?, CURRENT_TIMESTAMP) "
            "ON CONFLICT(id) DO UPDATE SET data = excluded.data, updated_at = CURRENT_TIMESTAMP",
            (json.dumps(config, ensure_ascii=False),)
        )
        conn.commit()

def load_prizes() -> List[Dict[str, Any]]:
    with sqlite_connect() as conn:
        fields = ", ".join(PRIZE_FIELDS)
        rows = conn.execute(f"SELECT {fields} FROM prizes ORDER BY sort_order ASC, id ASC").fetchall()
        return [normalize_prize(dict(r)) for r in rows]

def load_history() -> List[Dict[str, Any]]:
    with sqlite_connect() as conn:
        rows = conn.execute(f"{HISTORY_SELECT_SQL} ORDER BY h.id ASC").fetchall()
        return [dict(r) for r in rows]

def save_prizes(prizes: List[Dict[str, Any]], current_prizes: List[Dict[str, Any]]):
    existing_ids, delete_ids = compute_prize_diff(prizes, current_prizes)

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

def delete_last_record() -> Optional[int]:
    """가장 최근에 저장된 draw_history 레코드 1건을 삭제하고 삭제된 id 반환"""
    with sqlite_connect() as conn:
        row = conn.execute("SELECT id FROM draw_history ORDER BY id DESC LIMIT 1").fetchone()
        if not row:
            return None
        last_id = row["id"]
        conn.execute("DELETE FROM draw_history WHERE id = ?", (last_id,))
        conn.commit()
        return last_id

def clear_records():
    with sqlite_connect() as conn:
        conn.execute("DELETE FROM draw_history")
        conn.commit()
        print("[SUCCESS] 로컬 SQLite(lottery.db) 데이터가 초기화되었습니다.")

def save_access_log(ip: str, page_type: str, path: str, user_agent: str = ""):
    """페이지 접속 감사 로그(Audit Log) 저장"""
    try:
        with sqlite_connect() as conn:
            conn.execute(
                "INSERT INTO access_logs (ip, page_type, path, user_agent) VALUES (?, ?, ?, ?)",
                (ip, page_type, path, user_agent),
            )
            conn.commit()
    except Exception as e:
        print(f"[WARN] SQLite access log 저장 오류: {e}")

def load_access_logs(limit: int = 100) -> List[Dict[str, Any]]:
    """페이지 접속 감사 로그(Audit Log) 최신순 조회"""
    try:
        with sqlite_connect() as conn:
            rows = conn.execute(
                "SELECT id, ip, page_type, path, user_agent, created_at "
                "FROM access_logs ORDER BY id DESC LIMIT ?",
                (limit,)
            ).fetchall()
            return [dict(r) for r in rows]
    except Exception as e:
        print(f"[WARN] SQLite access log 조회 오류: {e}")
        return []

def cleanup_old_access_logs(hours: int = 24) -> int:
    """지정된 시간(기본 24시간) 이전의 오래된 접속 감사 로그 자동 삭제"""
    try:
        with sqlite_connect() as conn:
            cur = conn.execute(
                "DELETE FROM access_logs WHERE created_at < datetime('now', ?)",
                (f"-{hours} hours",),
            )
            deleted_count = cur.rowcount
            conn.commit()
            if deleted_count > 0:
                print(f"[INFO] SQLite: {deleted_count}건의 {hours}시간 경과 감사 로그를 정리했습니다.")
            return deleted_count
    except Exception as e:
        print(f"[WARN] SQLite 감사 로그 정리 오류: {e}")
        return 0

def clear_all_access_logs() -> int:
    """접속 감사 로그 전체 초기화/삭제"""
    try:
        with sqlite_connect() as conn:
            cur = conn.execute("DELETE FROM access_logs")
            deleted_count = cur.rowcount
            conn.commit()
            print(f"[INFO] SQLite: 전체 {deleted_count}건의 감사 로그를 초기화했습니다.")
            return deleted_count
    except Exception as e:
        print(f"[WARN] SQLite 감사 로그 전체 삭제 오류: {e}")
        return 0


