# 2026 서울청년정책네트워크 총회 실시간 현장 추첨 시스템

FastAPI + WebSocket + uv 기반의 실시간 반응형 현장 추첨 웹 애플리케이션입니다.  
현장 빔프로젝터/대형 스크린용 **디스플레이 페이지**와 운영진용 **관리자 콘솔**이 초저지연 WebSocket으로 실시간 연동됩니다.

---

## 🌟 주요 기능
1. **화면 분리 & 초저지연 실시간 연동 (WebSocket)**:
   - 운영진이 관리자 페이지에서 번호를 뽑으면 대형 스크린에 0.1초 만에 롤링 애니메이션 시작
2. **시각 및 청각 연출**:
   - 3.8초 긴장감 넘치는 디지털 슬롯머신 롤링 효과
   - 당첨 시 화려한 폭죽(Confetti) 및 팡파레 효과음 (Web Audio API 내장 신디사이저)
   - 유튜브 라이브 BGM 연동 및 관리자 원격 재생/일시정지/음소거(사운드 ON/OFF)/볼륨 제어
3. **사운드 상태 표시 & 원격 제어 일원화**:
   - 디스플레이 화면: 접속 즉시 사운드 기본 ON, 헤더에는 현재 소리 상태 배지(`🔊 사운드 ON` / `🔇 사운드 OFF`)만 표시
   - 관리자 화면: 현장 사운드 및 BGM의 모든 제어(재생, 일시정지, 음소거, 볼륨)를 원격에서 일괄 관리
4. **부재자 패스(넘어가기) 기능**:
   - 호명 시 부재중일 경우 [⏭️ 부재중 패스] 버튼으로 패스 처리
   - 스크린 현황판에 흐린 텍스트 및 취소선으로 투명하게 공개
5. **자유로운 환경 설정**:
   - 번호 범위(예: 1~200) 및 등수(1등 1명, 2등 3명, 3등 5명 등) 웹에서 즉시 추가/수정 가능
6. **Supabase 연동 & 안전한 로컬 SQLite Fallback**:
   - Supabase 클라우드 DB 연동 지원
   - Supabase가 없거나 연결이 불가능한 경우에도 **로컬 SQLite(`lottery.db`)**로 100% 자동 전환되어 모든 추첨 이력이 영구 보존됨

---

## 🛠️ 1. Supabase 설정 (선택 사항)

Supabase를 사용하려면 대시보드([supabase.com](https://supabase.com))의 **SQL Editor**에서 아래 쿼리를 1회 실행합니다 (미설정 시 로컬 SQLite `lottery.db`로 자동 동작):

```sql
-- db/sql/supabase/schema.sql 파일 참고
-- 등수(경품) 설정
CREATE TABLE prizes (
    id BIGSERIAL PRIMARY KEY,
    rank VARCHAR(50) NOT NULL,
    name VARCHAR(100) DEFAULT '',
    count INT NOT NULL DEFAULT 1,
    sort_order INT NOT NULL DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now())
);

-- 추첨 이력 (등수명/상품명은 prizes 와 JOIN 하여 조회)
CREATE TABLE draw_history (
    id BIGSERIAL PRIMARY KEY,
    prize_id BIGINT NOT NULL REFERENCES prizes(id) ON DELETE RESTRICT,
    drawn_number INT NOT NULL,
    status VARCHAR(20) NOT NULL, -- 'CONFIRMED' 또는 'PASSED'
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now())
);
```

> `prizes` 테이블이 비어 있으면 서버 시작 시 기본 등수(3등/2등/1등)가 자동으로 시드됩니다.

> **`config.json`** 은 번호 범위·BGM 기본값만 담는 파일로, 삭제되어도 기본값(1~200)으로 동작합니다. 관리자 페이지에서 변경한 번호 범위/BGM은 메모리에만 반영되며 파일을 수정하지 않습니다.

---

## ⚙️ 2. 환경 변수 설정 (`.env`)

`.env` 파일에 관리자 비밀번호와 Supabase 정보(선택)를 입력합니다:

```ini
ADMIN_PASSWORD=admin1234

# Supabase 연동 시 (미입력 시 로컬 SQLite로 자동 작동)
SUPABASE_URL=https://your-project-id.supabase.co
SUPABASE_KEY=your-supabase-key
```

---

## 🚀 3. uv 기반 로컬 실행 방법 (권장)

이 프로젝트는 초고속 파이썬 패키지 매니저 **uv**를 표준으로 사용합니다.

### 1) 의존성 설치 및 가상환경 동기화
```bash
uv sync
```

### 2) 개발 서버 실행
```bash
uv run uvicorn main:app --reload --port 8000
```

> **📌 참고: 가상환경 직접 활성화 후 실행할 경우**
> - **Windows (PowerShell)**:
>   ```powershell
>   .\.venv\Scripts\Activate.ps1
>   uvicorn main:app --reload --port 8000
>   ```
> - **macOS / Linux**:
>   ```bash
>   source .venv/bin/activate
>   uvicorn main:app --reload --port 8000
>   ```
> *※ 가상환경 활성화 없이 바로 실행하려면 항상 앞에 `uv run`을 붙여서 `uv run uvicorn main:app --reload --port 8000`으로 실행하세요.*

### 3) 접속 URL
- **현장 스크린 송출 화면**: [http://localhost:8000/display](http://localhost:8000/display) (또는 `/`)
- **관리자 진행 콘솔**: [http://localhost:8000/admin](http://localhost:8000/admin) (비밀번호: `admin1234`)

---

## ☁️ 4. 클라우드 호스팅 (Render.com 배포 가이드)

1. 이 프로젝트 코드를 **GitHub Repository**에 푸시합니다.
2. [Render.com 대시보드](https://dashboard.render.com) 접속 후 **New +** → **Web Service** 선택
3. 본인 GitHub 레포지토리 연결
4. 빌드 및 시작 명령어 설정:
   - **Build Command**: 
     ```bash
     pip install uv && uv sync --frozen
     ```
   - **Start Command**: 
     ```bash
     uv run uvicorn main:app --host 0.0.0.0 --port $PORT
     ```
5. **Environment Variables** 탭에서 환경 변수 등록:
   - `ADMIN_PASSWORD`: 행사 당일 사용할 관리자 비밀번호 (기본값: `admin1234`)
   - `SUPABASE_URL`: (권장) Supabase Project URL *(클라우드 배포 시 인스턴스 재시작 간 데이터 영구 보존을 위해 Supabase 연동 권장)*
   - `SUPABASE_KEY`: (권장) Supabase Key
6. **Deploy Web Service** 클릭 시 배포가 완료되며 공용 URL이 생성됩니다.


