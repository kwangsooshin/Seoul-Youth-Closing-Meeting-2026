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
                if isinstance(data, dict) and data.get("type"):
                    await manager.broadcast(data)
            except Exception:
                pass
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception:
        manager.disconnect(websocket)
