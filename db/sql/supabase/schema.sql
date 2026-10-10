-- Supabase (PostgreSQL) 용 스키마 DDL

-- prizes 테이블 생성
CREATE TABLE IF NOT EXISTS prizes (
    id BIGSERIAL PRIMARY KEY,
    rank VARCHAR(50) NOT NULL,
    name VARCHAR(100) DEFAULT '',
    count INT NOT NULL DEFAULT 1,
    sort_order INT NOT NULL DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now())
);

-- draw_history 테이블 생성 (prizes FK 연동)
CREATE TABLE IF NOT EXISTS draw_history (
    id BIGSERIAL PRIMARY KEY,
    prize_id BIGINT NOT NULL REFERENCES prizes(id) ON DELETE RESTRICT,
    drawn_number INT NOT NULL,
    status VARCHAR(20) NOT NULL, -- 'CONFIRMED' 또는 'PASSED'
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now())
);

-- app_config 테이블 생성 (번호 범위 및 BGM 등 JSONB 설정 저장)
CREATE TABLE IF NOT EXISTS app_config (
    id VARCHAR(50) PRIMARY KEY DEFAULT 'current',
    data JSONB NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now())
);
