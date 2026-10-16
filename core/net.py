import ipaddress
from typing import Optional, List
from starlette.requests import HTTPConnection


def _normalize_ip(raw_ip: Optional[str]) -> Optional[str]:
    """문자열이 유효한 IPv4/IPv6 주소인지 검증 후 정규화된 문자열 반환 (위조/비정상 문자열 차단)"""
    if not raw_ip:
        return None
    candidate = raw_ip.strip()
    if not candidate:
        return None
    # [IPv6]:port 형태 처리
    if candidate.startswith("[") and "]" in candidate:
        candidate = candidate[1:candidate.index("]")]
    # IPv4:port 형태 처리
    elif candidate.count(":") == 1 and "." in candidate:
        candidate = candidate.split(":", 1)[0]
    try:
        return str(ipaddress.ip_address(candidate))[:45]
    except ValueError:
        return None


def _is_trusted_proxy_peer(host: Optional[str]) -> bool:
    """직접 연결된 소켓 피어가 로컬/사설망 리버스 프록시(Render, Nginx, Cloudflare Tunnel 등)인지 확인"""
    norm = _normalize_ip(host)
    if not norm:
        return False
    try:
        ip_obj = ipaddress.ip_address(norm)
        return ip_obj.is_loopback or ip_obj.is_private or ip_obj.is_link_local
    except ValueError:
        return False


def get_client_ip(request: HTTPConnection) -> str:
    """
    클라이언트의 실제 IP 주소를 안전하게 추출합니다.
    직접 외부에서 연결된 클라이언트가 임의로 X-Forwarded-For / CF-Connecting-IP 헤더를 조작하는 것을 방어하기 위해
    신뢰할 수 있는 프록시 대역(사설/루프백)을 거친 경우에만 프록시 헤더를 신뢰하며, 모든 IP는 형식을 검증합니다.
    """
    socket_host = request.client.host if (request.client and request.client.host) else None
    normalized_socket_ip = _normalize_ip(socket_host)

    # 리버스 프록시(사설/로컬 대역) 경유 요청인 경우에만 포워딩 헤더 신뢰
    if _is_trusted_proxy_peer(socket_host):
        # 1. Cloudflare 환경
        cf_ip = _normalize_ip(request.headers.get("cf-connecting-ip"))
        if cf_ip:
            return cf_ip

        # 2. Nginx / Render 등 리버스 프록시 단일 헤더
        real_ip = _normalize_ip(request.headers.get("x-real-ip"))
        if real_ip:
            return real_ip

        # 3. X-Forwarded-For 체인 (프록시가 끝에 추가한 우측 IP 우선 검증하여 클라이언트 헤더 스푸핑 방지)
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            valid_ips = [
                ip for part in forwarded.split(",")
                if (ip := _normalize_ip(part)) is not None
            ]
            if valid_ips:
                # 프록시 체인에서 가장 마지막에 추가된 공인 IP 또는 우측 IP 선택
                for ip in reversed(valid_ips):
                    if not _is_trusted_proxy_peer(ip):
                        return ip
                return valid_ips[-1]

    if normalized_socket_ip:
        return normalized_socket_ip

    return "unknown"


def get_rate_limit_keys(request: HTTPConnection) -> List[str]:
    """
    로그인 무차별 대입(Brute-force) 방어를 위해 추출된 클라이언트 IP와
    실제 소켓 연결 IP를 모두 키 목록으로 반환하여 헤더 스푸핑 우회를 원천 차단합니다.
    """
    keys = [f"ip:{get_client_ip(request)}"]
    if request.client and request.client.host:
        sock_ip = _normalize_ip(request.client.host) or request.client.host[:45]
        sock_key = f"sock:{sock_ip}"
        if sock_key not in keys:
            keys.append(sock_key)
    return keys

