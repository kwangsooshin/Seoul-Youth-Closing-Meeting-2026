import os
from typing import List, Dict, Any, Optional

from . import sqlite_db
from . import supabase_db

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")

supabase_client = None
use_supabase = False

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
    global use_supabase
    default_cfg = fallback_config or {
        "min_number": 1,
        "max_number": 200,
        "bgm_youtube_url": "https://www.youtube.com/watch?v=ujCh9JIxCeA"
    }

    if use_supabase and supabase_client:
        try:
            cfg = supabase_db.load_config_db(supabase_client)
            if cfg:
                return {**default_cfg, **cfg}
        except Exception as e:
            print(f"[WARN] Supabase config 조회 실패 -> SQLite로 대체: {e}")

    # SQLite 조회
    cfg = sqlite_db.load_config_db()
    if cfg:
        return {**default_cfg, **cfg}

    return default_cfg

def save_app_config(config: Dict[str, Any]):
    """Supabase 우선 저장, 실패/오프라인 대비 SQLite에도 동기화 저장"""
    global use_supabase
    if use_supabase and supabase_client:
        try:
            supabase_db.save_config_db(supabase_client, config)
        except Exception as e:
            print(f"[WARN] Supabase config 저장 실패 -> SQLite로 대체 저장: {e}")
            use_supabase = False

    # 로컬 SQLite에도 항상 저장하여 무중단 보장
    try:
        sqlite_db.save_config_db(config)
    except Exception as e:
        print(f"[WARN] SQLite config 저장 실패: {e}")

def load_prizes() -> List[Dict[str, Any]]:
    global use_supabase
    if use_supabase and supabase_client:
        try:
            return supabase_db.load_prizes(supabase_client)
        except Exception as e:
            print(f"[WARN] Supabase 등수 조회 실패 -> SQLite로 대체: {e}")
            use_supabase = False
    return sqlite_db.load_prizes()

def load_history() -> List[Dict[str, Any]]:
    global use_supabase
    if use_supabase and supabase_client:
        try:
            return supabase_db.load_history(supabase_client)
        except Exception as e:
            print(f"[WARN] Supabase 이력 조회 실패 -> SQLite로 대체: {e}")
            use_supabase = False
    return sqlite_db.load_history()

def save_prizes(prizes: List[Dict[str, Any]], current_prizes: List[Dict[str, Any]]):
    global use_supabase
    if use_supabase and supabase_client:
        try:
            supabase_db.save_prizes(supabase_client, prizes, current_prizes)
            return
        except Exception as e:
            print(f"[WARN] Supabase 등수 저장 실패 -> SQLite로 대체 저장: {e}")
            use_supabase = False
    sqlite_db.save_prizes(prizes, current_prizes)

def save_record(record: dict, current_prizes: List[Dict[str, Any]]) -> dict:
    global use_supabase
    if use_supabase and supabase_client:
        try:
            res = supabase_db.save_record(supabase_client, record)
            if res:
                return res
        except Exception as e:
            print(f"[WARN] Supabase 저장 실패 -> SQLite로 대체 저장: {e}")
            use_supabase = False
    return sqlite_db.save_record(record, current_prizes)

def delete_last_record() -> Optional[int]:
    global use_supabase
    if use_supabase and supabase_client:
        try:
            return supabase_db.delete_last_record(supabase_client)
        except Exception as e:
            print(f"[WARN] Supabase 최근 기록 삭제 실패 -> SQLite로 대체: {e}")
            use_supabase = False
    return sqlite_db.delete_last_record()

def clear_records():
    global use_supabase
    if use_supabase and supabase_client:
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
    zone = os.getenv("ZONE", "dev").strip().lower()
    return {
        "type": "SUPABASE" if use_supabase else "SQLITE",
        "name": "Supabase 클라우드" if use_supabase else "로컬 SQLite (lottery.db)",
        "details": f"스키마: {schema} ({history_count}건)" if use_supabase else f"파일: lottery.db ({history_count}건)",
        "schema": schema,
        "zone": zone,
    }

def save_access_log(ip: str, page_type: str, path: str, user_agent: str = ""):
    """Supabase 우선 저장, 실패 시 SQLite 대체 저장 (localhost / 127.0.0.1 제외)"""
    global use_supabase
    if ip and ip.lower() in ("localhost", "127.0.0.1", "::1", "testclient"):
        return

    saved_supabase = False
    if use_supabase and supabase_client:
        try:
            supabase_db.save_access_log(supabase_client, ip, page_type, path, user_agent)
            saved_supabase = True
        except Exception as e:
            print(f"[WARN] Supabase access log 저장 실패 -> SQLite 대체 저장: {e}")

    # Supabase 저장이 되지 않았거나 오프라인인 경우 SQLite에 저장 (또는 무중단 백업)
    if not saved_supabase:
        try:
            sqlite_db.save_access_log(ip, page_type, path, user_agent)
        except Exception as e:
            print(f"[WARN] SQLite access log 저장 실패: {e}")

def load_access_logs(limit: int = 100) -> List[Dict[str, Any]]:
    """Supabase 우선 조회, 실패 시 SQLite 조회"""
    global use_supabase
    if use_supabase and supabase_client:
        try:
            return supabase_db.load_access_logs(supabase_client, limit)
        except Exception as e:
            print(f"[WARN] Supabase access log 조회 실패 -> SQLite 대체: {e}")
    return sqlite_db.load_access_logs(limit)

def cleanup_old_access_logs(hours: int = 24):
    """Supabase 및 SQLite에서 24시간 지난 오래된 접속 감사 로그 자동 정리"""
    global use_supabase
    if use_supabase and supabase_client:
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
    global use_supabase
    deleted_count = 0
    if use_supabase and supabase_client:
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


