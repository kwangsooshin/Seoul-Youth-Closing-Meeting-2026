-- prizes 테이블 생성 (등수 및 경품 설정)
CREATE TABLE IF NOT EXISTS prizes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rank TEXT NOT NULL,
    name TEXT DEFAULT '',
    count INTEGER NOT NULL DEFAULT 1,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- draw_history 테이블 생성 (추첨 이력 - prizes 참조)
CREATE TABLE IF NOT EXISTS draw_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    prize_id INTEGER NOT NULL REFERENCES prizes(id) ON DELETE RESTRICT,
    drawn_number INTEGER NOT NULL,
    status TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
