import time
from typing import List, Dict, Any, Optional
from core.config import load_config
from db import load_prizes, load_history, get_db_info, load_app_config

# 대기화면 해제 세션 지속 제한 시간: 3시간 (초 단위: 10,800초)
SESSION_TIMEOUT_SECONDS = 3 * 3600


class LotteryState:
    """인메모리 추첨 세션 상태 및 통계 관리"""
    def __init__(self):
        self.config: Dict[str, Any] = load_config()
        self.prizes: List[Dict[str, Any]] = []
        self.history: List[Dict[str, Any]] = []
        self.pending_draw: Optional[Dict[str, Any]] = None
        self.is_started: bool = False  # 현장 추첨 대기화면 해제 여부
        self.session_started_at: Optional[float] = None  # 대기화면 해제 시작 시각 (epoch seconds)
        self.selected_prize_id: Optional[int] = None  # 관리자가 현재 선택한 추첨 등수 ID
        self.audio_state: Dict[str, Any] = {
            "master_muted": False,
            "bgm_paused": True,  # 기본값 BGM OFF
            "sfx_muted": False,
            "volume": 30
        }

    def start_session(self):
        """추첨 세션 시작 (대기화면 해제 및 시작 타임스탬프 기록)"""
        self.is_started = True
        self.session_started_at = time.time()

    def stop_session(self):
        """추첨 세션 종료 (대기화면 복귀)"""
        self.is_started = False
        self.session_started_at = None

    def sync_from_db(self):
        """DB에서 앱 설정, 등수 목록 및 추첨 이력 동기화"""
        try:
            self.config = load_app_config(self.config)
            self.prizes = load_prizes()
            self.history = load_history()
            info = get_db_info(len(self.history))
            print(f"[SUCCESS] {info['name']}에서 설정, 등수 {len(self.prizes)}개, 이력 {len(self.history)}건을 불러왔습니다.")

            # 선택된 등수가 없거나 유효하지 않으면 미완료 등수 또는 첫 번째 등수로 기본 설정
            if self.prizes:
                valid_ids = {p["id"] for p in self.prizes}
                if self.selected_prize_id not in valid_ids:
                    used_by_prize: Dict[int, int] = {}
                    for h in self.history:
                        if h.get("status") == "CONFIRMED":
                            used_by_prize[h["prize_id"]] = used_by_prize.get(h["prize_id"], 0) + 1
                    # 완료되지 않은 첫 번째 등수 찾기
                    next_p = next((p for p in self.prizes if used_by_prize.get(p["id"], 0) < p["count"]), None)
                    self.selected_prize_id = next_p["id"] if next_p else self.prizes[0]["id"]
        except Exception as e:
            print(f"[WARN] DB 조회 실패: {e}")

    def get_used_numbers(self) -> set:
        """이미 확정되거나 패스된 번호 집합"""
        return {item["drawn_number"] for item in self.history}

    def find_prize(self, prize_id: int) -> Optional[Dict[str, Any]]:
        """등수 ID로 등수 정보 조회"""
        return next((p for p in self.prizes if p["id"] == prize_id), None)

    def get_stats(self) -> Dict[str, Any]:
        """현재 당첨 및 패스 현황 통계 계산"""
        used_numbers = self.get_used_numbers()
        total_range = self.config["max_number"] - self.config["min_number"] + 1
        remaining_pool_count = max(0, total_range - len(used_numbers))

        confirmed_by_prize: Dict[int, List[int]] = {}
        passed_numbers: List[Dict[str, Any]] = []

        for item in self.history:
            if item["status"] == "CONFIRMED":
                confirmed_by_prize.setdefault(item["prize_id"], []).append(item["drawn_number"])
            elif item["status"] == "PASSED":
                passed_numbers.append(item)

        # 등수별 진행률
        prize_status = []
        for p in self.prizes:
            confirmed = confirmed_by_prize.get(p["id"], [])
            prize_status.append({
                "id": p["id"],
                "rank": p["rank"],
                "name": p.get("name", ""),
                "target_count": p["count"],
                "confirmed_count": len(confirmed),
                "confirmed_numbers": confirmed,
                "is_completed": len(confirmed) >= p["count"]
            })

        return {
            "config": {**self.config, "prizes": self.prizes},
            "history": self.history,
            "prize_status": prize_status,
            "passed_numbers": passed_numbers,
            "used_numbers": list(used_numbers),
            "total_tickets": total_range,
            "remaining_pool_count": remaining_pool_count,
            "current_pending_draw": self.pending_draw,
            "is_lottery_started": self.is_started,
            "session_started_at": self.session_started_at,
            "session_timeout_seconds": SESSION_TIMEOUT_SECONDS,
            "selected_prize_id": self.selected_prize_id,
            "db_info": get_db_info(len(self.history)),
            "audio_state": self.audio_state
        }


state = LotteryState()
