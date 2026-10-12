import json
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from core.websocket import manager
from core.state import state

router = APIRouter(tags=["WebSocket"])


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    # 첫 연결 시 현재 전체 상태 전송
    try:
        await websocket.send_json({"type": "SYNC_STATE", "data": state.get_stats()})
        while True:
            text = await websocket.receive_text()
            try:
                data = json.loads(text)
                if isinstance(data, dict):
                    msg_type = data.get("type")
                    # 보안: 클라이언트(현장 스크린)에서 웹소켓으로 수신 허용되는 이벤트는
                    # 롤링 애니메이션 완료(DRAW_ROLLING_COMPLETE)만 허용 (임의 DRAW_RESET, 확정 이벤트 주입 차단)
                    if msg_type == "DRAW_ROLLING_COMPLETE":
                        # 진행 중인 추첨 번호와 일치하는 경우에만 관리자 화면에 알림 브로드캐스트
                        if state.pending_draw and data.get("number") == state.pending_draw.get("number"):
                            await manager.broadcast({
                                "type": "DRAW_ROLLING_COMPLETE",
                                "number": state.pending_draw.get("number")
                            })
            except Exception:
                pass
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception:
        manager.disconnect(websocket)
