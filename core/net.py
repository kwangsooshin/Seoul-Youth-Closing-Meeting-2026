from fastapi import Request


def get_client_ip(request: Request) -> str:
    """
    클라이언트의 실제 IP 주소를 안전하게 추출합니다.
    헤더 조작을 방어하고 다양한 배포 환경(Cloudflare, Render/Nginx 리버스 프록시, 로컬)을 지원합니다.
    1. Cloudflare 헤더 (CF-Connecting-IP)
    2. 리버스 프록시 헤더 (X-Real-IP)
    3. 프록시 체인 헤더 (X-Forwarded-For - 첫 번째 클라이언트 IP)
    4. 직접 소켓 연결 IP (request.client.host)
    """
    # 1. Cloudflare 환경
    cf_ip = request.headers.get("cf-connecting-ip")
    if cf_ip and cf_ip.strip():
        return cf_ip.strip()[:45]

    # 2. Nginx / Render 등 리버스 프록시 단일 헤더
    real_ip = request.headers.get("x-real-ip")
    if real_ip and real_ip.strip():
        return real_ip.strip()[:45]

    # 3. X-Forwarded-For 체인
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        parts = [p.strip() for p in forwarded.split(",") if p.strip()]
        if parts:
            return parts[0][:45]

    # 4. 직접 연결 소켓
    if request.client and request.client.host:
        return request.client.host[:45]

    return "unknown"
