import json
import time
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from core.websocket import manager
from core.state import state

router = APIRouter(tags=["WebSocket"])

MAX_WS_MESSAGE_LENGTH = 1024
MIN_ROLLING_ELAPSED_SECONDS = 3.0


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    connected = await manager.connect(websocket)
    if not connected:
        return

    # 첫 연결 시 현재 전체 상태 전송
    try:
        await websocket.send_json({"type": "SYNC_STATE", "data": state.get_stats()})
        while True:
            text = await websocket.receive_text()
            if not text or len(text) > MAX_WS_MESSAGE_LENGTH:
                continue
            try:
                data = json.loads(text)
                if isinstance(data, dict):
                    msg_type = data.get("type")
                    # 보안: 클라이언트(현장 스크린)에서 웹소켓으로 수신 허용되는 이벤트는
                    # 롤링 애니메이션 완료(DRAW_ROLLING_COMPLETE)만 허용하며,
                    # 최소 롤링 시간 경과 여부 및 추첨당 1회만 브로드캐스트되도록 제한 (증폭/조기 활성화 방어)
                    if msg_type == "DRAW_ROLLING_COMPLETE":
                        pending = state.pending_draw
                        if (
                            pending
                            and not pending.get("rolling_completed")
                            and data.get("number") == pending.get("number")
                            and (time.time() - pending.get("drawn_at", 0) >= MIN_ROLLING_ELAPSED_SECONDS)
                        ):
                            pending["rolling_completed"] = True
                            await manager.broadcast({
                                "type": "DRAW_ROLLING_COMPLETE",
                                "number": pending.get("number")
                            })
            except Exception:
                pass
    except (WebSocketDisconnect, Exception):
        pass
    finally:
        manager.disconnect(websocket)

