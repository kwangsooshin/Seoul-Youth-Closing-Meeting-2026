-- ==============================================================================
-- 2026 서울청년정책네트워크 총회 현장 추첨
-- Supabase (PostgreSQL) 멀티 존(dev / service) 스키마 정의 및 보안(RLS·권한) 설정 SQL
-- 
-- 사용 방법:
-- 1. Supabase 대시보드 -> 왼쪽 메뉴 [SQL Editor] 접속
-- 2. 본 스크립트 전체를 복사하여 붙여넣고 [Run] 실행
-- 3. [Project Settings] -> [Data API] -> [Exposed schemas] 항목에
--    'dev', 'service' 를 등록합니다. (보안을 위해 미사용 'public'은 제외 권장)
-- ==============================================================================

-- ------------------------------------------------------------------------------
-- 0. 레거시 public 스키마 미사용 테이블 보안 조치 (rls_disabled_in_public 해결)
--    과거 public 스키마에 생성된 테이블이 남아 있으면 Supabase Security Advisor에서
--    'rls_disabled_in_public' 경고가 발생합니다.
--    본 프로젝트는 'dev' 및 'service' 스키마만 사용하므로 public 내 동일 테이블에
--    RLS를 활성화하고 외부(anon, authenticated) 접근 권한을 회수합니다.
--    (만약 public 테이블이 완전히 불필요하다면 아래 주석 처리된 DROP 문을 실행하세요)
-- ------------------------------------------------------------------------------
-- DROP TABLE IF EXISTS public.draw_history, public.prizes, public.app_config, public.access_logs CASCADE;

DO $$
DECLARE
    tbl TEXT;
BEGIN
    FOREACH tbl IN ARRAY ARRAY['prizes', 'draw_history', 'app_config', 'access_logs']
    LOOP
        IF EXISTS (
            SELECT 1 FROM pg_tables WHERE schemaname = 'public' AND tablename = tbl
        ) THEN
            EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY;', tbl);
            EXECUTE format('REVOKE ALL ON TABLE public.%I FROM anon, authenticated;', tbl);
            EXECUTE format('GRANT select, insert, update, delete ON TABLE public.%I TO service_role;', tbl);
        END IF;
    END LOOP;
END $$;

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
-- 4. Row-Level Security (RLS) 활성화 (보안 취약점 rls_disabled 완벽 해결)
--    - 모든 테이블에 RLS를 활성화하여 외부에서 Project URL 및 anon/publishable 키로
--      무단 조회/수정/삭제하는 것을 원천 차단합니다.
--    - 백엔드 서버가 사용하는 `service_role` (또는 `sb_secret_...` 키)는
--      기본적으로 RLS를 우회(BYPASSRLS)하므로 별도 정책 없이도 안전하게 모든 작업이 가능합니다.
--    - 만일의 경우를 대비해 `service_role` 전용 명시적 정책도 함께 등록합니다.
-- ------------------------------------------------------------------------------
ALTER TABLE dev.prizes ENABLE ROW LEVEL SECURITY;
ALTER TABLE dev.draw_history ENABLE ROW LEVEL SECURITY;
ALTER TABLE dev.app_config ENABLE ROW LEVEL SECURITY;
ALTER TABLE dev.access_logs ENABLE ROW LEVEL SECURITY;

ALTER TABLE service.prizes ENABLE ROW LEVEL SECURITY;
ALTER TABLE service.draw_history ENABLE ROW LEVEL SECURITY;
ALTER TABLE service.app_config ENABLE ROW LEVEL SECURITY;
ALTER TABLE service.access_logs ENABLE ROW LEVEL SECURITY;

-- service_role 명시적 허용 정책 (중복 실행 시 안전하도록 DROP 후 생성)
DO $$
DECLARE
    sch TEXT;
    tbl TEXT;
BEGIN
    FOREACH sch IN ARRAY ARRAY['dev', 'service']
    LOOP
        FOREACH tbl IN ARRAY ARRAY['prizes', 'draw_history', 'app_config', 'access_logs']
        LOOP
            EXECUTE format('DROP POLICY IF EXISTS "service_role_all_access" ON %I.%I;', sch, tbl);
            EXECUTE format(
                'CREATE POLICY "service_role_all_access" ON %I.%I FOR ALL TO service_role USING (true) WITH CHECK (true);',
                sch, tbl
            );
        END LOOP;
    END LOOP;
END $$;

-- ------------------------------------------------------------------------------
-- 5. Data API 명시적 권한(GRANT) 설정 (2026년 10월 30일 Supabase 정책 변경 대응)
--    - 백엔드 전용 구조이므로 외부 공개 역할(anon, authenticated)의 권한은 회수(REVOKE)하고
--      오직 백엔드 서버 역할(service_role)에만 명시적으로 GRANT 합니다.
-- ------------------------------------------------------------------------------
-- 5-1. anon, authenticated 불필요 권한 회수 (최소 권한 원칙)
REVOKE ALL ON ALL TABLES IN SCHEMA dev FROM anon, authenticated;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA dev FROM anon, authenticated;
REVOKE ALL ON ALL TABLES IN SCHEMA service FROM anon, authenticated;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA service FROM anon, authenticated;

-- 5-2. dev 스키마 service_role 명시적 권한 부여
GRANT USAGE ON SCHEMA dev TO service_role;
GRANT select, insert, update, delete ON TABLE dev.prizes TO service_role;
GRANT select, insert, update, delete ON TABLE dev.draw_history TO service_role;
GRANT select, insert, update, delete ON TABLE dev.app_config TO service_role;
GRANT select, insert, update, delete ON TABLE dev.access_logs TO service_role;
GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA dev TO service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA dev REVOKE ALL ON TABLES FROM anon, authenticated;
ALTER DEFAULT PRIVILEGES IN SCHEMA dev GRANT select, insert, update, delete ON TABLES TO service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA dev GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO service_role;

-- 5-3. service 스키마 service_role 명시적 권한 부여
GRANT USAGE ON SCHEMA service TO service_role;
GRANT select, insert, update, delete ON TABLE service.prizes TO service_role;
GRANT select, insert, update, delete ON TABLE service.draw_history TO service_role;
GRANT select, insert, update, delete ON TABLE service.app_config TO service_role;
GRANT select, insert, update, delete ON TABLE service.access_logs TO service_role;
GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA service TO service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA service REVOKE ALL ON TABLES FROM anon, authenticated;
ALTER DEFAULT PRIVILEGES IN SCHEMA service GRANT select, insert, update, delete ON TABLES TO service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA service GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO service_role;
