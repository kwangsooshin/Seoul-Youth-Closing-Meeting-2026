import os
from typing import List, Dict, Any, Optional, Callable, TypeVar

from core.config import DEFAULT_CONFIG, ZONE
from . import sqlite_db
from . import supabase_db

T = TypeVar("T")

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")

supabase_client = None
use_supabase = False


def _is_supabase_active() -> bool:
    return bool(use_supabase and supabase_client is not None)


def _query_with_fallback(
    action_name: str,
    supabase_fn: Callable[[Any], T],
    sqlite_fn: Callable[[], T],
) -> T:
    """Supabase 우선 조회 후 일시적 오류 발생 시 로컬 SQLite로 안전하게 대체 조회"""
    if _is_supabase_active():
        try:
            return supabase_fn(supabase_client)
        except Exception as e:
            print(f"[WARN] Supabase {action_name} 실패 -> SQLite로 대체: {e}")
    return sqlite_fn()


def init_db(default_prizes: List[Dict[str, Any]], default_config: Optional[Dict[str, Any]] = None):
    """DB 초기화: Supabase 우선 검증 후 미설정/실패 시 SQLite 초기화"""
    global supabase_client, use_supabase

    # 1. 로컬 SQLite 항상 테이블 준비 및 초기 시드
    sqlite_db.init_sqlite(default_prizes, default_config)

    # 2. Supabase 클라이언트 연결 시도
    if SUPABASE_URL and SUPABASE_KEY and "your-project" not in SUPABASE_URL:
        try:
            from supabase import create_client
            supabase_client = create_client(SUPABASE_URL, SUPABASE_KEY)
            print("[SUCCESS] Supabase 클라이언트 연결 시도 성공")
            # Supabase 테이블 유효성 검사 및 초기 시드
            supabase_db.seed_prizes_if_empty(supabase_client, default_prizes)
            if default_config:
                try:
                    supabase_db.seed_config_if_empty(supabase_client, default_config)
                except Exception as e:
                    print(f"[INFO] Supabase app_config 시드 대기 (테이블 생성 전 등): {e}")
            supabase_db.load_history(supabase_client)
            use_supabase = True
            schema = supabase_db.get_schema()
            print(f"[SUCCESS] Supabase '{schema}' 스키마 테이블 연동 완료")
        except Exception as e:
            schema = supabase_db.get_schema()
            print(f"[INFO] Supabase '{schema}' 스키마 연결/테이블 불가 ({e}) -> 로컬 SQLite 모드로 동작합니다.")
            use_supabase = False
    else:
        print("[INFO] Supabase 설정이 없어 로컬 SQLite(lottery.db) 모드로 동작합니다.")
        use_supabase = False


def load_app_config(fallback_config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Supabase 우선, 실패 시 SQLite에서 앱 설정 로드 (기본값 병합)"""
    default_cfg = fallback_config or dict(DEFAULT_CONFIG)

    if _is_supabase_active():
        try:
            cfg = supabase_db.load_config_db(supabase_client)
            if cfg:
                return {**default_cfg, **cfg}
        except Exception as e:
            print(f"[WARN] Supabase config 조회 실패 -> SQLite로 대체: {e}")

    cfg = sqlite_db.load_config_db()
    if cfg:
        return {**default_cfg, **cfg}

    return default_cfg


def save_app_config(config: Dict[str, Any]):
    """Supabase 우선 저장, 실패/오프라인 대비 SQLite에도 동기화 저장"""
    if _is_supabase_active():
        try:
            supabase_db.save_config_db(supabase_client, config)
        except Exception as e:
            print(f"[WARN] Supabase config 저장 실패 -> SQLite로 대체 저장: {e}")

    try:
        sqlite_db.save_config_db(config)
    except Exception as e:
        print(f"[WARN] SQLite config 저장 실패: {e}")


def load_prizes() -> List[Dict[str, Any]]:
    return _query_with_fallback(
        "등수 조회",
        lambda client: supabase_db.load_prizes(client),
        sqlite_db.load_prizes,
    )


def load_history() -> List[Dict[str, Any]]:
    return _query_with_fallback(
        "이력 조회",
        lambda client: supabase_db.load_history(client),
        sqlite_db.load_history,
    )


def save_prizes(prizes: List[Dict[str, Any]], current_prizes: List[Dict[str, Any]]):
    if _is_supabase_active():
        try:
            supabase_db.save_prizes(supabase_client, prizes, current_prizes)
        except Exception as e:
            print(f"[WARN] Supabase 등수 저장 실패 -> SQLite로 대체 저장: {e}")

    # 로컬 SQLite에도 동기화 백업 저장
    try:
        sqlite_db.save_prizes(prizes, sqlite_db.load_prizes())
    except Exception as e:
        print(f"[WARN] SQLite 등수 동기화 저장 실패: {e}")


def save_record(record: dict, current_prizes: List[Dict[str, Any]]) -> dict:
    supabase_res = None
    if _is_supabase_active():
        try:
            supabase_res = supabase_db.save_record(supabase_client, record)
        except Exception as e:
            print(f"[WARN] Supabase 기록 저장 실패 -> SQLite로 대체 저장: {e}")

    try:
        sqlite_res = sqlite_db.save_record(record, current_prizes)
    except Exception as e:
        if supabase_res:
            print(f"[WARN] SQLite 기록 백업 저장 실패: {e}")
            return supabase_res
        raise

    return supabase_res or sqlite_res


def delete_last_record() -> Optional[int]:
    supabase_deleted = None
    if _is_supabase_active():
        try:
            supabase_deleted = supabase_db.delete_last_record(supabase_client)
        except Exception as e:
            print(f"[WARN] Supabase 최근 기록 삭제 실패 -> SQLite로 대체: {e}")

    try:
        sqlite_deleted = sqlite_db.delete_last_record()
    except Exception as e:
        print(f"[WARN] SQLite 최근 기록 삭제 실패: {e}")
        sqlite_deleted = None

    return supabase_deleted if supabase_deleted is not None else sqlite_deleted


def clear_records():
    if _is_supabase_active():
        try:
            supabase_db.clear_records(supabase_client)
        except Exception as e:
            print(f"[WARN] Supabase 초기화 오류: {e}")

    try:
        sqlite_db.clear_records()
    except Exception as e:
        print(f"[WARN] SQLite 초기화 오류: {e}")


def get_db_info(history_count: int) -> Dict[str, str]:
    schema = supabase_db.get_schema()
    active = _is_supabase_active()
    return {
        "type": "SUPABASE" if active else "SQLITE",
        "name": "Supabase 클라우드" if active else "로컬 SQLite (lottery.db)",
        "details": f"스키마: {schema} ({history_count}건)" if active else f"파일: lottery.db ({history_count}건)",
        "schema": schema,
        "zone": ZONE,
    }


def save_access_log(ip: str, page_type: str, path: str, user_agent: str = ""):
    """Supabase 우선 저장, 실패 시 SQLite 대체 저장"""
    saved_supabase = False
    if _is_supabase_active():
        try:
            supabase_db.save_access_log(supabase_client, ip, page_type, path, user_agent)
            saved_supabase = True
        except Exception as e:
            print(f"[WARN] Supabase access log 저장 실패 -> SQLite 대체 저장: {e}")

    if not saved_supabase:
        try:
            sqlite_db.save_access_log(ip, page_type, path, user_agent)
        except Exception as e:
            print(f"[WARN] SQLite access log 저장 실패: {e}")


def load_access_logs(limit: int = 100) -> List[Dict[str, Any]]:
    """Supabase 우선 조회, 실패 시 SQLite 조회"""
    return _query_with_fallback(
        "access log 조회",
        lambda client: supabase_db.load_access_logs(client, limit),
        lambda: sqlite_db.load_access_logs(limit),
    )


def cleanup_old_access_logs(hours: int = 24):
    """Supabase 및 SQLite에서 24시간 지난 오래된 접속 감사 로그 자동 정리"""
    if _is_supabase_active():
        try:
            supabase_db.cleanup_old_access_logs(supabase_client, hours)
        except Exception as e:
            print(f"[WARN] Supabase 감사 로그 정리 오류: {e}")

    try:
        sqlite_db.cleanup_old_access_logs(hours)
    except Exception as e:
        print(f"[WARN] SQLite 감사 로그 정리 오류: {e}")


def clear_all_access_logs() -> int:
    """Supabase 및 SQLite에서 모든 접속 감사 로그 초기화/삭제"""
    deleted_count = 0
    if _is_supabase_active():
        try:
            deleted_count = supabase_db.clear_all_access_logs(supabase_client)
        except Exception as e:
            print(f"[WARN] Supabase 감사 로그 전체 삭제 오류: {e}")

    try:
        sqlite_deleted = sqlite_db.clear_all_access_logs()
        if not deleted_count:
            deleted_count = sqlite_deleted
    except Exception as e:
        print(f"[WARN] SQLite 감사 로그 전체 삭제 오류: {e}")

    return deleted_count



