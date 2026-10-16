import asyncio
from collections import defaultdict
from typing import List, Dict
from fastapi import WebSocket
from core.net import get_client_ip


class ConnectionManager:
    """실시간 웹소켓 연결 및 브로드캐스트 관리자 (전체/IP별 연결 수 제한 및 끊긴 세션 자동 회수)"""
    def __init__(self, max_connections: int = 120, max_per_ip: int = 25):
        self.active_connections: List[WebSocket] = []
        self._ip_connections: Dict[str, List[WebSocket]] = defaultdict(list)
        self.max_connections = max_connections
        self.max_per_ip = max_per_ip

    async def connect(self, websocket: WebSocket) -> bool:
        """새 클라이언트 연결 수락 (최대 연결 수 및 IP당 연결 수 초과 시 차단하여 슬롯 고갈 DoS 방지)"""
        client_ip = get_client_ip(websocket)

        if len(self.active_connections) >= self.max_connections:
            try:
                await websocket.close(code=1008, reason="Connection limit reached")
            except Exception:
                pass
            return False

        if len(self._ip_connections[client_ip]) >= self.max_per_ip:
            # 동일 IP에서 과도한 연결 시 가장 오래된 유휴 연결 1개를 정리하고 새 연결 허용 (새로고침 유실 방지 및 DoS 방어)
            oldest_ws = self._ip_connections[client_ip][0]
            self.disconnect(oldest_ws)
            try:
                await oldest_ws.close(code=1000, reason="Replaced by newer connection")
            except Exception:
                pass

        await websocket.accept()
        self.active_connections.append(websocket)
        self._ip_connections[client_ip].append(websocket)
        return True

    def disconnect(self, websocket: WebSocket):
        """연결 목록 및 IP별 추적 목록에서 제거"""
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        for ip, conns in list(self._ip_connections.items()):
            if websocket in conns:
                conns.remove(websocket)
                if not conns:
                    self._ip_connections.pop(ip, None)

    async def _send_safe(self, connection: WebSocket, message: dict) -> bool:
        try:
            await asyncio.wait_for(connection.send_json(message), timeout=3.0)
            return True
        except Exception:
            return False

    async def broadcast(self, message: dict):
        """활성 연결 클라이언트 전체에 병렬 브로드캐스트 (느린 클라이언트로 인한 지연 차단 및 죽은 연결 자동 정리)"""
        connections = list(self.active_connections)
        if not connections:
            return

        results = await asyncio.gather(
            *(self._send_safe(conn, message) for conn in connections),
            return_exceptions=True,
        )
        for conn, ok in zip(connections, results):
            if ok is not True:
                self.disconnect(conn)


manager = ConnectionManager()

