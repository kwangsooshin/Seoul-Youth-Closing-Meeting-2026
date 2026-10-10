-- Supabase (PostgreSQL) 데이터베이스 스키마

-- 1. prizes 테이블 (추첨 등수 및 경품 설정)
CREATE TABLE IF NOT EXISTS prizes (
    id BIGSERIAL PRIMARY KEY,
    rank VARCHAR(50) NOT NULL,
    name VARCHAR(100) DEFAULT '',
    count INT NOT NULL DEFAULT 1,
    sort_order INT NOT NULL DEFAULT 0, -- 관리자 화면 정렬 순서 (0부터 오름차순)
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now())
);

-- 2. draw_history 테이블 (추첨 당첨/패스 이력 - prizes 외래키 연동)
CREATE TABLE IF NOT EXISTS draw_history (
    id BIGSERIAL PRIMARY KEY,
    prize_id BIGINT NOT NULL REFERENCES prizes(id) ON DELETE RESTRICT, -- 이력 존재 시 등수 삭제 방지
    drawn_number INT NOT NULL,
    status VARCHAR(20) NOT NULL, -- 'CONFIRMED'(당첨 확정) 또는 'PASSED'(부재중 패스)
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now())
);

-- 3. app_config 테이블 (번호 범위, BGM 링크 등 앱 설정 JSONB 저장)
CREATE TABLE IF NOT EXISTS app_config (
    id VARCHAR(50) PRIMARY KEY DEFAULT 'current',
    data JSONB NOT NULL, -- JSONB 형식 설정 데이터
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now())
);
