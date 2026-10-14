from typing import List
from fastapi import WebSocket


class ConnectionManager:
    """실시간 웹소켓 연결 및 브로드캐스트 관리자 (연결 수 제한 및 끊긴 세션 자동 회수)"""
    def __init__(self, max_connections: int = 100):
        self.active_connections: List[WebSocket] = []
        self.max_connections = max_connections

    async def connect(self, websocket: WebSocket) -> bool:
        """새 클라이언트 연결 수락 (최대 연결 수 초과 시 차단하여 DoS 방지)"""
        if len(self.active_connections) >= self.max_connections:
            try:
                await websocket.close(code=1008, reason="Connection limit reached")
            except Exception:
                pass
            return False
        await websocket.accept()
        self.active_connections.append(websocket)
        return True

    def disconnect(self, websocket: WebSocket):
        """연결 목록에서 제거"""
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        """활성 연결 클라이언트 전체에 브로드캐스트 (실패한 연결은 메모리 누수 방지를 위해 자동 정리)"""
        dead_connections = []
        for connection in list(self.active_connections):
            try:
                await connection.send_json(message)
            except Exception:
                dead_connections.append(connection)

        for dead in dead_connections:
            self.disconnect(dead)


manager = ConnectionManager()
