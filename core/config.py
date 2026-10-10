import os
import sys
import json
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
CONFIG_PATH = BASE_DIR / "config.json"

ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin1234")

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
    """config.json은 읽기 전용 기본값 파일. 없거나 손상되어도 DEFAULT_CONFIG로 동작한다.
    관리자 페이지에서 변경한 값은 메모리에만 반영되며 파일에 기록하지 않는다."""
    cfg = dict(DEFAULT_CONFIG)
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            for key in DEFAULT_CONFIG:
                if key in data:
                    cfg[key] = data[key]
        except Exception as e:
            print(f"설정 파일 읽기 오류 (기본값 사용): {e}")
    return cfg
