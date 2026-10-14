import os
import sys
from pathlib import Path
from typing import Dict, Any, List
from dotenv import load_dotenv

# Windows cp949 콘솔 인코딩 에러 방지
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# .env 로드
load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin1234")

# 실행 환경 존 (dev: 개발용, service: 실서비스 운영용)
ZONE = os.getenv("ZONE", "dev").strip().lower()
SCHEMA_NAME = "service" if ZONE in ("service", "prod", "production") else "dev"

if ZONE in ("service", "prod", "production") and ADMIN_PASSWORD == "admin1234":
    print("[SECURITY WARNING] 운영 환경(ZONE=service)에서 기본 비밀번호('admin1234')가 사용되고 있습니다. 보안을 위해 환경변수 ADMIN_PASSWORD를 반드시 안전한 값으로 변경하세요!")

DEFAULT_BGM_URL = "https://www.youtube.com/watch?v=ujCh9JIxCeA"

DEFAULT_CONFIG: Dict[str, Any] = {
    "min_number": 1,
    "max_number": 200,
    "bgm_youtube_url": DEFAULT_BGM_URL,
}

# prizes 테이블이 비어 있을 때 최초 1회 시드되는 기본 등수
DEFAULT_PRIZES: List[Dict[str, Any]] = [
    {"rank": "3등", "count": 5, "name": "스타벅스 e카드 교환권"},
    {"rank": "2등", "count": 3, "name": "무선 이어폰"},
    {"rank": "1등", "count": 1, "name": "아이패드 10세대"},
]


def load_config() -> Dict[str, Any]:
    """초기 기본 설정 반환 (이후 DB sync_from_db를 통해 Supabase/SQLite에서 로드)"""
    return dict(DEFAULT_CONFIG)
