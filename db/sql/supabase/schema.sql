-- ==============================================================================
-- 2026 서울청년정책네트워크 총회 현장 추첨
-- Supabase (PostgreSQL) 멀티 존(dev / service) 스키마 정의 SQL
-- 
-- 사용 방법:
-- 1. Supabase 대시보드 -> 왼쪽 메뉴 [SQL Editor] 접속
-- 2. 본 스크립트 전체를 복사하여 붙여넣고 [Run] 실행
-- 3. [Project Settings] -> [API] -> [PostgREST Settings]의 [Exposed schemas] 항목에
--    기본값인 public 외에 'dev', 'service' 를 추가합니다. (예: public, dev, service)
-- ==============================================================================

-- ------------------------------------------------------------------------------
-- 1. 스키마(네임스페이스) 생성
-- ------------------------------------------------------------------------------
CREATE SCHEMA IF NOT EXISTS dev;
CREATE SCHEMA IF NOT EXISTS service;

-- ------------------------------------------------------------------------------
-- 2. 개발용 (dev) 스키마 테이블 생성
-- ------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dev.prizes (
    id BIGSERIAL PRIMARY KEY,
    rank VARCHAR(50) NOT NULL,
    name VARCHAR(100) DEFAULT '',
    count INT NOT NULL DEFAULT 1,
    sort_order INT NOT NULL DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now())
);

CREATE TABLE IF NOT EXISTS dev.draw_history (
    id BIGSERIAL PRIMARY KEY,
    prize_id BIGINT NOT NULL REFERENCES dev.prizes(id) ON DELETE RESTRICT,
    drawn_number INT NOT NULL,
    status VARCHAR(20) NOT NULL, -- 'CONFIRMED' 또는 'PASSED'
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now())
);

CREATE TABLE IF NOT EXISTS dev.app_config (
    id VARCHAR(50) PRIMARY KEY DEFAULT 'current',
    data JSONB NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now())
);

CREATE TABLE IF NOT EXISTS dev.access_logs (
    id BIGSERIAL PRIMARY KEY,
    ip VARCHAR(50) NOT NULL,
    page_type VARCHAR(50) NOT NULL,
    path VARCHAR(255) NOT NULL,
    user_agent TEXT DEFAULT '',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now())
);

-- ------------------------------------------------------------------------------
-- 3. 실서비스 운영용 (service) 스키마 테이블 생성
-- ------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS service.prizes (
    id BIGSERIAL PRIMARY KEY,
    rank VARCHAR(50) NOT NULL,
    name VARCHAR(100) DEFAULT '',
    count INT NOT NULL DEFAULT 1,
    sort_order INT NOT NULL DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now())
);

CREATE TABLE IF NOT EXISTS service.draw_history (
    id BIGSERIAL PRIMARY KEY,
    prize_id BIGINT NOT NULL REFERENCES service.prizes(id) ON DELETE RESTRICT,
    drawn_number INT NOT NULL,
    status VARCHAR(20) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now())
);

CREATE TABLE IF NOT EXISTS service.app_config (
    id VARCHAR(50) PRIMARY KEY DEFAULT 'current',
    data JSONB NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now())
);

CREATE TABLE IF NOT EXISTS service.access_logs (
    id BIGSERIAL PRIMARY KEY,
    ip VARCHAR(50) NOT NULL,
    page_type VARCHAR(50) NOT NULL,
    path VARCHAR(255) NOT NULL,
    user_agent TEXT DEFAULT '',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now())
);

-- ------------------------------------------------------------------------------
-- 4. API 역할(service_role, anon, authenticated) 접근 및 시퀀스 권한 부여
-- [보안 권장사항]
-- 백엔드 서버(.env의 SUPABASE_KEY)에 'service_role' 키를 사용하는 경우,
-- 외부에서 anon 키로 DB에 직접 접근하지 못하도록 아래 GRANT 문에서 'anon, authenticated'를
-- 제외하고 'service_role'에만 권한을 부여하는 것을 권장합니다.
-- ------------------------------------------------------------------------------
-- dev 스키마 권한
GRANT USAGE ON SCHEMA dev TO anon, authenticated, service_role;
GRANT ALL ON ALL TABLES IN SCHEMA dev TO anon, authenticated, service_role;
GRANT ALL ON ALL SEQUENCES IN SCHEMA dev TO anon, authenticated, service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA dev GRANT ALL ON TABLES TO anon, authenticated, service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA dev GRANT ALL ON SEQUENCES TO anon, authenticated, service_role;

-- service 스키마 권한
GRANT USAGE ON SCHEMA service TO anon, authenticated, service_role;
GRANT ALL ON ALL TABLES IN SCHEMA service TO anon, authenticated, service_role;
GRANT ALL ON ALL SEQUENCES IN SCHEMA service TO anon, authenticated, service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA service GRANT ALL ON TABLES TO anon, authenticated, service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA service GRANT ALL ON SEQUENCES TO anon, authenticated, service_role;

