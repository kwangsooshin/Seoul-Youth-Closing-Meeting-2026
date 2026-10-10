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

Supabase 클라우드 데이터베이스를 연동하려면, Supabase 대시보드([supabase.com](https://supabase.com))의 **SQL Editor**에서 스키마 정의 파일을 복사하여 1회 실행합니다 (미설정 시 로컬 SQLite `lottery.db`로 자동 무중단 동작):

👉 **테이블 생성 SQL 파일:** [`db/sql/supabase/schema.sql`](db/sql/supabase/schema.sql)

> 💡 `prizes` 및 `app_config` 테이블이 생성되어 비어 있으면 서버 시작 시 기본 등수(3등/2등/1등)와 기본 설정이 자동으로 시드됩니다.
> 💡 번호 범위·BGM 설정 및 등수 정보는 데이터베이스(Supabase / 로컬 SQLite)에 안전하게 영구 저장됩니다.

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
   - **배포 도메인 예시**: `https://<내-Render-도메인>.onrender.com`
   - **현장 스크린 송출 화면**: `https://<내-Render-도메인>.onrender.com/display` (또는 `/`)
   - **관리자 진행 콘솔**: `https://<내-Render-도메인>.onrender.com/admin`
   - **헬스체크 엔드포인트**: `https://<내-Render-도메인>.onrender.com/healthz`

---

## 🤖 5. UptimeRobot 설정 가이드 (Render & Supabase 상시 활성화 / Keep-Alive)

Render 무료 플랜은 **15분 동안 인바운드 트래픽이 없으면 자동으로 슬립(Spin Down)** 상태로 전환되어, 다음 방문 시 50초 이상의 심각한 지연(콜드 스타트)이 발생합니다. 또한 Supabase 무료 플랜 역시 장기간 데이터베이스 쿼리가 없으면 프로젝트가 비활성화(Pause)될 수 있습니다.

무료 모니터링 도구인 **[UptimeRobot](https://uptimerobot.com)**을 연동하면 **Render 웹 서버와 Supabase 데이터베이스 모두를 24시간 중단 없이 상시 활성화 상태로 유지**할 수 있습니다.

### 💡 동작 원리
UptimeRobot이 주기적으로 `/healthz` 엔드포인트를 호출(HTTP HEAD 권장)하면:
1. **Render 인스턴스 활성화**: HTTP 요청을 수신하여 15분 슬립 타이머가 계속 초기화됩니다.
2. **Supabase DB 활성화**: `HEAD` 요청 시에도 백그라운드 태스크로 `access_logs` 테이블에 헬스체크 접속 로그(`page_type: healthcheck`)가 자동으로 기록(INSERT)되므로 Supabase 프로젝트의 Pause가 방지됩니다.
3. **자동 용량 관리**: 24시간이 지난 오래된 헬스체크 로그는 서버의 백그라운드 스케줄러가 매 시간 자동으로 정리하므로 용량 걱정이 없습니다.

---

### ⚙️ UptimeRobot 등록 단계 (무료)

1. **[UptimeRobot](https://uptimerobot.com)** 회원가입 및 로그인 (무료 플랜 5분 간격 모니터링 50개 제공)
2. 대시보드 좌측 상단 **[+ Add New Monitor]** 버튼 클릭
3. 모니터링 설정값 입력:
   - **Monitor Type**: `HTTP(s)` *(무료 플랜 정책에 따라 HTTP Method는 `HEAD` 선택 권장 - 본문 전송 없이도 Supabase 로그가 정상 기록됨)*
   - **Friendly Name**: `서울청년 추첨 시스템 (Render & Supabase Keep-Alive)`
   - **URL (or IP)**: `https://<내-Render-도메인>.onrender.com/healthz`
   - **Monitoring Interval**: `5 minutes` *(Render 15분 슬립 방지를 위해 5분 권장)*
   - **Monitor Timeout**: `30 seconds`
4. 우측 하단 **[Create Monitor]** 클릭하여 등록 완료

---

### 🔍 동작 확인 방법
- 웹 브라우저에서 직접 `https://<내-Render-도메인>.onrender.com/healthz` 접속 시 아래와 같은 JSON 응답이 반환됩니다:
  ```json
  {
    "status": "healthy",
    "service": "seoul-youth-lottery",
    "keep_alive": true,
    "client_ip": "..."
  }
  ```
- 관리자 콘솔([`/admin`](http://localhost:8000/admin) 또는 `https://<내-Render-도메인>.onrender.com/admin`)의 **`📋 접속 감사 로그`** 탭에서 녹색 **`🤖 healthcheck`** 뱃지와 함께 UptimeRobot의 핑 기록이 실시간으로 확인됩니다.



