-- 로컬 SQLite (lottery.db) 데이터베이스 스키마

-- 1. prizes 테이블 (추첨 등수 및 경품 설정)
CREATE TABLE IF NOT EXISTS prizes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rank TEXT NOT NULL,
    name TEXT DEFAULT '',
    count INTEGER NOT NULL DEFAULT 1,
    sort_order INTEGER NOT NULL DEFAULT 0, -- 관리자 화면 정렬 순서 (0부터 오름차순)
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 2. draw_history 테이블 (추첨 당첨/패스 이력 - prizes 외래키 연동)
CREATE TABLE IF NOT EXISTS draw_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    prize_id INTEGER NOT NULL REFERENCES prizes(id) ON DELETE RESTRICT, -- 이력 존재 시 등수 삭제 방지
    drawn_number INTEGER NOT NULL,
    status TEXT NOT NULL, -- 'CONFIRMED'(당첨 확정) 또는 'PASSED'(부재중 패스)
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 3. app_config 테이블 (번호 범위, BGM 링크 등 앱 설정 JSON 저장)
CREATE TABLE IF NOT EXISTS app_config (
    id TEXT PRIMARY KEY DEFAULT 'current',
    data TEXT NOT NULL, -- JSON 형식 설정 데이터
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 4. access_logs 테이블 (페이지 접속 감사 로그 - IP 및 페이지 유형)
CREATE TABLE IF NOT EXISTS access_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ip TEXT NOT NULL,
    page_type TEXT NOT NULL, -- 'display', 'admin' 등
    path TEXT NOT NULL,
    user_agent TEXT DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
